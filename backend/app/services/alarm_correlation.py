"""
Alarm Correlation Service.

Adds business context to pre-correlated alarms from OSS vendor systems.
This service does NOT replace vendor correlation engines (e.g., Nokia NetAct, Ericsson ENM).
It consumes their output and enriches it with topology proximity, temporal clustering,
and business impact (revenue-at-risk, emergency service detection).

Used by: WS4 (service_impact API router).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from backend.app.schemas.service_impact import AlarmCluster, CustomerImpact, ServiceImpactSummary

logger = logging.getLogger(__name__)

# Temporal clustering window: alarms within this window are candidates for grouping
TEMPORAL_WINDOW_MINUTES = 5


class AlarmCorrelationService:
    """
    Enriches pre-correlated OSS alarms with business context.

    Positioning: This service consumes pre-correlated alarms from OSS and adds
    business context (revenue-at-risk, emergency service escalation, customer impact).
    It does not replace vendor correlation engines.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    def correlate_alarms(self, alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Group related alarms into clusters using three strategies:
        1. Topology proximity: same entity or connected entities
        2. Temporal clustering: alarms within TEMPORAL_WINDOW_MINUTES
        3. Symptom similarity: same alarm_type

        Returns a list of cluster dicts with cluster metadata.
        """
        if not alarms:
            return []

        clusters: List[Dict[str, Any]] = []
        assigned: set = set()

        for i, alarm in enumerate(alarms):
            if i in assigned:
                continue

            cluster_alarms = [alarm]
            assigned.add(i)

            alarm_time = self._parse_time(alarm.get("raised_at"))
            alarm_entity = alarm.get("entity_id")
            alarm_type = alarm.get("alarm_type")

            for j, other in enumerate(alarms):
                if j in assigned:
                    continue

                other_time = self._parse_time(other.get("raised_at"))
                other_entity = other.get("entity_id")
                other_type = other.get("alarm_type")

                # Strategy 1: Same entity
                same_entity = alarm_entity and other_entity and alarm_entity == other_entity

                # Strategy 2: Temporal proximity
                temporal_match = False
                if alarm_time and other_time:
                    diff = abs((alarm_time - other_time).total_seconds())
                    temporal_match = diff <= TEMPORAL_WINDOW_MINUTES * 60

                # Strategy 3: Same alarm type
                same_type = alarm_type and other_type and alarm_type == other_type

                if same_entity or (temporal_match and same_type):
                    cluster_alarms.append(other)
                    assigned.add(j)

            # Determine cluster severity
            severities = [a.get("severity", "minor") for a in cluster_alarms]
            cluster_severity = self._highest_severity(severities)

            # Check for emergency service
            is_emergency = any(
                a.get("entity_type") == "EMERGENCY_SERVICE" or a.get("is_emergency_service")
                for a in cluster_alarms
            )
            if is_emergency:
                cluster_severity = "critical"

            # Determine root cause entity (most frequent entity in cluster)
            entity_ids = [a.get("entity_id") for a in cluster_alarms if a.get("entity_id")]
            root_entity_id = max(set(entity_ids), key=entity_ids.count) if entity_ids else None

            clusters.append({
                "alarm_count": len(cluster_alarms),
                "alarms": cluster_alarms,
                "severity": cluster_severity,
                "is_emergency_service": is_emergency,
                "root_cause_entity_id": root_entity_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        return clusters

    def calculate_noise_reduction(self, raw_count: int, clustered_count: int) -> float:
        """
        Calculate the noise reduction percentage.
        e.g., 100 raw alarms → 10 clusters = 90% reduction.
        """
        if raw_count == 0:
            return 0.0
        reduction = ((raw_count - clustered_count) / raw_count) * 100.0
        return round(max(0.0, min(100.0, reduction)), 2)

    async def get_customer_impact(self, cluster_entity_ids: List[str], tenant_id: str) -> List[Dict[str, Any]]:
        """
        Traverse topology to find customers impacted by the given entity IDs.
        Queries the topology_entities and customers tables with strict tenant isolation.
        """
        if not cluster_entity_ids:
            return []

        impacted_customers = []
        try:
            # Finding S-1 Fix: Enforce tenant isolation
            query = text("""
                SELECT c.id, c.name, c.external_id, c.tenant_id
                FROM customers c
                WHERE c.associated_site_id IN :site_ids
                AND c.tenant_id = :tid
            """)
            result = await self.session.execute(query, {"site_ids": tuple(cluster_entity_ids), "tid": tenant_id})
            rows = result.fetchall()
            for row in rows:
                impacted_customers.append({
                    "customer_id": str(row[0]),
                    "customer_name": row[1] or "Unknown",
                    "customer_external_id": row[2] or str(row[0]),
                    "tenant_id": row[3],
                })
        except Exception as e:
            logger.warning(f"Could not fetch customer impact: {e}")

        return impacted_customers

    def _parse_time(self, time_val: Any) -> Optional[datetime]:
        """Parse a time value to datetime."""
        if isinstance(time_val, datetime):
            return time_val
        if isinstance(time_val, str):
            try:
                return datetime.fromisoformat(time_val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _highest_severity(self, severities: List[str]) -> str:
        """Return the highest severity from a list."""
        order = {"critical": 4, "major": 3, "minor": 2, "warning": 1}
        return max(severities, key=lambda s: order.get(s, 0), default="minor")
