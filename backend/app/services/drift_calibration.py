"""
Drift Detection Calibration Service — Task 7.2 (Amendment #24)

Tracks the false positive rate of drift detections over a configurable window.
Recommends threshold adjustment if FP rate exceeds 20%.

The 15% KPI drift threshold is now configurable via settings.drift_threshold_pct.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_false_positive_rate(db: AsyncSession, tenant_id: str) -> dict:
    """
    Compute the drift detection false positive rate over the configured window.

    A false positive is a drift detection where:
    - Pedkai issued a recommendation
    - The engineer dismissed it (marked as false positive via feedback)

    Returns:
        {
            "window_days": int,
            "total_detections": int,
            "true_positives": int,      # Approved recommendations
            "false_positives": int,     # Dismissed as noise
            "false_positive_rate": float,  # 0.0 – 1.0
            "current_threshold_pct": float,
            "recommendation": str,
        }
    """
    window_start = datetime.now(timezone.utc) - timedelta(
        days=settings.drift_false_positive_window_days
    )

    try:
        # Count total drift detections (decision traces) in window
        total_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM decision_traces
                WHERE tenant_id = :tid
                AND created_at >= :since
            """),
            {"tid": tenant_id, "since": window_start},
        )
        total = total_result.scalar() or 0

        # Count false positives (dismissed recommendations)
        fp_result = await db.execute(
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
