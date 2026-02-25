"""
Drift Detection Calibration Service — Task 7.2 (Amendment #24)

Tracks the false positive rate of drift detections over a configurable window.
Recommends threshold adjustment if FP rate exceeds 20%.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text
from contextlib import asynccontextmanager

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class DriftCalibrationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _get_session(self, session: Optional[AsyncSession] = None):
        if session:
            yield session
        else:
            async with self.session_factory() as new_session:
                try:
                    yield new_session
                    await new_session.commit()
                except Exception:
                    await new_session.rollback()
                    raise
                finally:
                    await new_session.close()

    async def get_false_positive_rate(self, tenant_id: str, session: Optional[AsyncSession] = None) -> Dict:
        """
        Compute the drift detection false positive rate over the configured window.
        """
        window_start = datetime.now(timezone.utc) - timedelta(
            days=settings.drift_false_positive_window_days
        )

        try:
            async with self._get_session(session) as s:
                # Count total drift detections (decision traces) in window
                total_result = await s.execute(
                    text("""
                        SELECT COUNT(*) FROM decision_traces
                        WHERE tenant_id = :tid
                        AND created_at >= :since
                    """),
                    {"tid": tenant_id, "since": window_start},
                )
                total = total_result.scalar() or 0

                # Count false positives (dismissed recommendations)
                fp_result = await s.execute(
                    text("""
                        SELECT COUNT(*) FROM decision_traces
                        WHERE tenant_id = :tid
                        AND created_at >= :since
                        AND status = 'dismissed'
                    """),
                    {"tid": tenant_id, "since": window_start},
                )
                false_positives = fp_result.scalar() or 0

            true_positives = total - false_positives
            fp_rate = round(false_positives / total, 4) if total > 0 else 0.0

            # Threshold recommendation
            current_threshold = settings.drift_threshold_pct
            if fp_rate > 0.20:
                recommended_threshold = round(current_threshold * 1.1, 1)  # Raise by 10%
                recommendation = (
                    f"False positive rate {fp_rate:.1%} exceeds 20% threshold. "
                    f"Recommend increasing DRIFT_THRESHOLD_PCT from {current_threshold}% "
                    f"to {recommended_threshold}% to reduce noise."
                )
            elif fp_rate < 0.05 and total > 20:
                recommended_threshold = round(current_threshold * 0.95, 1)  # Lower by 5%
                recommendation = (
                    f"False positive rate {fp_rate:.1%} is very low with adequate sample size. "
                    f"Recommend reducing DRIFT_THRESHOLD_PCT from {current_threshold}% "
                    f"to {recommended_threshold}% for earlier detection."
                )
            else:
                recommendation = (
                    f"False positive rate {fp_rate:.1%} is within acceptable range. "
                    f"No threshold adjustment recommended."
                )

            return {
                "window_days": settings.drift_false_positive_window_days,
                "total_detections": total,
                "true_positives": true_positives,
                "false_positives": false_positives,
                "false_positive_rate": fp_rate,
                "current_threshold_pct": current_threshold,
                "recommendation": recommendation,
            }

        except Exception as e:
            logger.error(f"Drift calibration query failed: {e}")
            return {
                "window_days": settings.drift_false_positive_window_days,
                "total_detections": 0,
                "false_positive_rate": 0.0,
                "current_threshold_pct": settings.drift_threshold_pct,
                "recommendation": f"Calibration unavailable: {e}",
            }
