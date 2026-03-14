"""
DivergenceScorer — Evaluation-only scoring module.

Compares reconciliation engine output (reconciliation_results) against
pre-seeded ground-truth labels (divergence_manifest) to compute
precision, recall, and F1 scores.

IMPORTANT: This module is strictly for offline evaluation and development
benchmarking. It must NEVER be called from the operational detection
pipeline. The ReconciliationEngine must not import or reference this module.

Ground-truth tables accessed (evaluation schema):
  - divergence_manifest

Operational tables read (for comparison only):
  - reconciliation_results
  - reconciliation_runs
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Divergence types that can appear in both manifest and engine output
SCORED_TYPES = [
    "dark_node",
    "phantom_node",
    "identity_mutation",
    "dark_attribute",
    "dark_edge",
    "phantom_edge",
]


class DivergenceScorer:
    """
    Scores reconciliation engine output against ground-truth labels.

    This is an evaluation tool, not part of the operational pipeline.
    It reads from divergence_manifest (ground truth) and reconciliation_results
    (engine output) to compute how well the engine performed.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def score(self, tenant_id: str) -> dict[str, Any]:
        """
        Compute overall and per-type precision/recall/F1 against the
        divergence_manifest for the most recent reconciliation run.
        """
        # Get latest run
        run_row = await self.session.execute(
            text(
                "SELECT * FROM reconciliation_runs "
                "WHERE tenant_id = :tid ORDER BY started_at DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
        run = run_row.mappings().fetchone()
        if not run:
            return {"error": "No reconciliation run found for this tenant."}

        # Check if manifest table exists and has data
        try:
            manifest_total = await self._scalar(
                "SELECT COUNT(*) FROM divergence_manifest WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
        except Exception:
            return {
                "error": "divergence_manifest table not found. "
                "Ground-truth data has not been loaded for scoring.",
            }

        if manifest_total == 0:
            return {
                "run_id": run["run_id"],
                "tenant_id": tenant_id,
                "note": "No ground-truth labels found in divergence_manifest. "
                "Scoring is not possible without evaluation data.",
                "overall": {
                    "manifest_count": 0,
                    "detected_in_manifest": 0,
                    "recall": 0.0,
                    "precision": 0.0,
                    "f1": 0.0,
                },
                "by_type": [],
            }

        # Overall scoring
        overall_hits = await self._scalar(
            """
            SELECT COUNT(*)
            FROM divergence_manifest dm
            WHERE dm.tenant_id = :tid
              AND EXISTS (
                  SELECT 1 FROM reconciliation_results rr
                  WHERE rr.tenant_id = :tid
                    AND rr.target_id = dm.target_id
                    AND rr.divergence_type = dm.divergence_type
              )
            """,
            {"tid": tenant_id},
        )

        total_detected = await self._scalar(
            "SELECT COUNT(*) FROM reconciliation_results WHERE tenant_id = :tid",
            {"tid": tenant_id},
        )

        overall_recall = overall_hits / max(manifest_total, 1)
        overall_precision = overall_hits / max(total_detected, 1)
        overall_f1 = (
            2 * overall_precision * overall_recall / (overall_precision + overall_recall)
            if (overall_precision + overall_recall) > 0
            else 0.0
        )

        # Per-type scoring
        per_type = []
        for div_type in SCORED_TYPES:
            m_count = await self._scalar(
                "SELECT COUNT(*) FROM divergence_manifest "
                "WHERE tenant_id = :tid AND divergence_type = :dt",
                {"tid": tenant_id, "dt": div_type},
            )
            d_count = await self._scalar(
                "SELECT COUNT(*) FROM reconciliation_results "
                "WHERE tenant_id = :tid AND divergence_type = :dt",
                {"tid": tenant_id, "dt": div_type},
            )
            hits = await self._scalar(
                """
                SELECT COUNT(*)
                FROM divergence_manifest dm
                WHERE dm.tenant_id = :tid AND dm.divergence_type = :dt
                  AND EXISTS (
                      SELECT 1 FROM reconciliation_results rr
                      WHERE rr.tenant_id = :tid
                        AND rr.target_id = dm.target_id
                        AND rr.divergence_type = :dt
                  )
                """,
                {"tid": tenant_id, "dt": div_type},
            )

            recall = hits / max(m_count, 1)
            precision = hits / max(d_count, 1)
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )

            per_type.append(
                {
                    "type": div_type,
                    "manifest_count": m_count,
                    "engine_detected": d_count,
                    "hits": hits,
                    "recall": round(recall, 4),
                    "precision": round(precision, 4),
                    "f1": round(f1, 4),
                }
            )

        return {
            "run_id": run["run_id"],
            "tenant_id": tenant_id,
            "overall": {
                "manifest_count": manifest_total,
                "detected_in_manifest": overall_hits,
                "total_engine_detected": total_detected,
                "recall": round(overall_recall, 4),
                "precision": round(overall_precision, 4),
                "f1": round(overall_f1, 4),
            },
            "by_type": per_type,
            "note": (
                "This scoring compares the signal-based engine output against "
                "pre-seeded ground-truth labels (divergence_manifest). "
                "The engine does NOT use these labels during detection — "
                "they are used here for offline accuracy measurement only."
            ),
        }

    async def _scalar(self, sql: str, params: dict) -> int:
        result = await self.session.execute(text(sql), params)
        val = result.scalar()
        return int(val) if val is not None else 0
