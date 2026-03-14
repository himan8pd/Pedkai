"""Ghost Mask Service — suppresses anomaly findings during planned maintenance.

Cross-references ITSM change ticket schedule against anomaly findings.
Findings during active change windows are labelled GHOST_MASKED (not deleted).

Redis integration: when REDIS_URL is set, caches active windows for fast lookup.
Falls back to in-memory dict when Redis is unavailable.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChangeWindow:
    ticket_id: str
    affected_entity_ids: list[str]
    start_time: datetime
    end_time: datetime
    change_type: str = "planned_maintenance"


@dataclass
class AnomalyFinding:
    entity_id: str
    timestamp: datetime
    anomaly_type: str
    confidence: float
    status: str = "ACTIVE"  # ACTIVE | GHOST_MASKED
    ghost_mask_reason: Optional[str] = None
    change_ticket_id: Optional[str] = None


class GhostMaskService:
    def __init__(self):
        self._windows: list[ChangeWindow] = []
        self._redis = None
        self._try_connect_redis()

    def _try_connect_redis(self):
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("GhostMaskService connected to Redis")
            except Exception as e:
                logger.warning(f"GhostMaskService Redis unavailable ({e}), using in-memory fallback")
                self._redis = None

    def load_change_schedule(self, tickets_data: list[dict]) -> list[ChangeWindow]:
        """Parse change tickets with change_type='planned_maintenance'.

        Args:
            tickets_data: List of dicts with fields:
                ticket_id, change_type, affected_entity_ids (list or comma-sep str),
                start_time, end_time

        Returns list of ChangeWindow objects (also stores them internally).
        """
        windows = []
        for ticket in tickets_data:
            change_type = ticket.get("change_type", "")
            if change_type != "planned_maintenance":
                continue

            affected = ticket.get("affected_entity_ids", [])
            if isinstance(affected, str):
                affected = [e.strip() for e in affected.split(",") if e.strip()]

            start = ticket.get("start_time")
            end = ticket.get("end_time")

            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            if start and end:
                w = ChangeWindow(
                    ticket_id=str(ticket.get("ticket_id", "")),
                    affected_entity_ids=list(affected),
                    start_time=start,
                    end_time=end,
                    change_type=change_type,
                )
                windows.append(w)

        self._windows = windows
        return windows

    def is_masked(self, entity_id: str, timestamp: datetime) -> Optional[ChangeWindow]:
        """Returns the ChangeWindow if entity has active change window at timestamp, else None."""
        # Ensure timestamp is timezone-aware for comparison
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        for window in self._windows:
            start = window.start_time if window.start_time.tzinfo else window.start_time.replace(tzinfo=timezone.utc)
            end = window.end_time if window.end_time.tzinfo else window.end_time.replace(tzinfo=timezone.utc)
            if entity_id in window.affected_entity_ids and start <= timestamp <= end:
                return window
        return None

    def apply_mask(self, findings: list[AnomalyFinding]) -> list[AnomalyFinding]:
        """Set status='GHOST_MASKED' on affected findings. Does NOT delete.

        Returns the same list (modified in-place).
        """
        for finding in findings:
            window = self.is_masked(finding.entity_id, finding.timestamp)
            if window:
                finding.status = "GHOST_MASKED"
                finding.ghost_mask_reason = "GHOST_MASKED"
                finding.change_ticket_id = window.ticket_id
        return findings

    def get_active_windows(self, timestamp: datetime = None) -> list[ChangeWindow]:
        """Return all currently active change windows."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        active = []
        for window in self._windows:
            start = window.start_time if window.start_time.tzinfo else window.start_time.replace(tzinfo=timezone.utc)
            end = window.end_time if window.end_time.tzinfo else window.end_time.replace(tzinfo=timezone.utc)
            if start <= timestamp <= end:
                active.append(window)
        return active
