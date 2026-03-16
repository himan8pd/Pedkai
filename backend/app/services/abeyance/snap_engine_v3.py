"""
Snap Engine v3.0 — mask-aware weighted scoring with per-dimension columns.

LLD v3.0 §3: Five scoring dimensions, mask enforcement, weight redistribution,
Sidak correction, disconfirmation penalty integration.

Invariants: INV-3, INV-7, INV-8, INV-10, INV-11, INV-NEW-1..3, INV-14.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    SnapDecisionRecordORM,
    VALID_TRANSITIONS,
)
from backend.app.services.abeyance.events import (
    ProvenanceLogger,
    RedisNotifier,
    FragmentStateChange,
)

logger = logging.getLogger(__name__)

# v3 weight profiles (LLD §3.4) — 5 dimensions: w_sem, w_topo, w_temp, w_oper, w_ent
WEIGHT_PROFILES_V3: dict[str, dict[str, float]] = {
    "DARK_EDGE":         {"w_sem": 0.15, "w_topo": 0.30, "w_temp": 0.10, "w_oper": 0.15, "w_ent": 0.30},
    "DARK_NODE":         {"w_sem": 0.25, "w_topo": 0.10, "w_temp": 0.10, "w_oper": 0.20, "w_ent": 0.35},
    "IDENTITY_MUTATION": {"w_sem": 0.10, "w_topo": 0.15, "w_temp": 0.10, "w_oper": 0.20, "w_ent": 0.45},
    "PHANTOM_CI":        {"w_sem": 0.20, "w_topo": 0.15, "w_temp": 0.10, "w_oper": 0.25, "w_ent": 0.30},
    "DARK_ATTRIBUTE":    {"w_sem": 0.25, "w_topo": 0.10, "w_temp": 0.10, "w_oper": 0.25, "w_ent": 0.30},
}

BASE_SNAP_THRESHOLD = 0.75
NEAR_MISS_THRESHOLD = 0.55
AFFINITY_THRESHOLD = 0.40
MAX_CANDIDATES = 200
_TEMPORAL_TAU: dict[str, float] = {
    "TICKET_TEXT": 270, "ALARM": 90, "TELEMETRY_EVENT": 60,
    "CLI_OUTPUT": 180, "CHANGE_RECORD": 365, "CMDB_DELTA": 90,
}
CHANGE_PROXIMITY_GAMMA = 0.3


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _cosine_similarity(a, b) -> float:
    a_arr = np.asarray(a, dtype=np.float64)
    b_arr = np.asarray(b, dtype=np.float64)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    union = len(set_a | set_b)
    return len(set_a & set_b) / union if union > 0 else 0.0


def _sidak_threshold(base: float, k: int) -> float:
    if k <= 1:
        return base
    return 1.0 - (1.0 - base) ** (1.0 / k)


class SnapEngineV3:
    """v3 mask-aware snap engine with per-dimension scores."""

    def __init__(
        self,
        provenance: ProvenanceLogger,
        notifier: Optional[RedisNotifier] = None,
    ):
        self._provenance = provenance
        self._notifier = notifier or RedisNotifier()
        # Runtime weight overrides from Outcome Calibration (Loop A)
        self._weight_overrides: dict[str, dict[str, float]] = {}

    def set_weight_overrides(self, overrides: dict[str, dict[str, float]]) -> None:
        """Accept calibrated weights from Outcome Calibration (Loop A read-only)."""
        self._weight_overrides = overrides

    def _get_weights(self, profile: str) -> dict[str, float]:
        return self._weight_overrides.get(profile, WEIGHT_PROFILES_V3.get(profile, WEIGHT_PROFILES_V3["DARK_EDGE"]))

    # --- Dimension availability (INV-11) ---

    @staticmethod
    def _available_dimensions(
        frag_a: AbeyanceFragmentORM, frag_b: AbeyanceFragmentORM,
    ) -> dict[str, bool]:
        """Determine which dimensions are available for this pair."""
        return {
            "semantic": bool(frag_a.mask_semantic and frag_b.mask_semantic),
            "topological": bool(frag_a.mask_topological and frag_b.mask_topological),
            "temporal": True,  # Always available
            "operational": bool(frag_a.mask_operational and frag_b.mask_operational),
            "entity_overlap": True,  # Always available
        }

    @staticmethod
    def _redistribute_weights(
        base_weights: dict[str, float], available: dict[str, bool],
    ) -> dict[str, float]:
        """Renormalize weights for available dimensions only (LLD §3.3)."""
        dim_to_key = {
            "semantic": "w_sem", "topological": "w_topo", "temporal": "w_temp",
            "operational": "w_oper", "entity_overlap": "w_ent",
        }
        total_avail = sum(
            base_weights[dim_to_key[d]] for d, avail in available.items() if avail
        )
        if total_avail <= 0:
            # Temporal + entity_overlap always available => should never happen
            return base_weights
        adjusted = {}
        for dim, key in dim_to_key.items():
            if available[dim]:
                adjusted[key] = base_weights[key] / total_avail
            else:
                adjusted[key] = 0.0
        return adjusted

    # --- Per-dimension scoring ---

    def _compute_per_dimension_scores(
        self,
        frag_a: AbeyanceFragmentORM,
        frag_b: AbeyanceFragmentORM,
        entities_a: set[str],
        entities_b: set[str],
        available: dict[str, bool],
    ) -> dict[str, Optional[float]]:
        scores: dict[str, Optional[float]] = {}

        # Semantic (INV-NEW-3: no cosine on NULL)
        if available["semantic"]:
            scores["semantic"] = _clamp(_cosine_similarity(frag_a.emb_semantic, frag_b.emb_semantic))
        else:
            scores["semantic"] = None

        # Topological
        if available["topological"]:
            scores["topological"] = _clamp(_cosine_similarity(frag_a.emb_topological, frag_b.emb_topological))
        else:
            scores["topological"] = None

        # Temporal (always valid)
        if frag_a.emb_temporal is not None and frag_b.emb_temporal is not None:
            scores["temporal"] = _clamp(_cosine_similarity(frag_a.emb_temporal, frag_b.emb_temporal))
        else:
            scores["temporal"] = 0.0

        # Operational
        if available["operational"]:
            scores["operational"] = _clamp(_cosine_similarity(frag_a.emb_operational, frag_b.emb_operational))
        else:
            scores["operational"] = None

        # Entity overlap (always computable)
        scores["entity_overlap"] = _clamp(_jaccard(entities_a, entities_b))

        return scores

    # --- Temporal modifier ---

    def _compute_temporal_modifier(
        self,
        new_time: Optional[datetime], stored_time: Optional[datetime],
        source_type: str,
    ) -> float:
        """Temporal modifier in [0.5, 1.0] — can only attenuate."""
        if not new_time or not stored_time:
            return 0.75
        tau = _TEMPORAL_TAU.get(source_type, 90.0)
        age_days = abs((new_time - stored_time).total_seconds()) / 86400.0
        age_factor = math.exp(-age_days / tau)
        # Diurnal alignment
        new_h = new_time.hour + new_time.minute / 60.0
        stored_h = stored_time.hour + stored_time.minute / 60.0
        cos_sim = (
            math.sin(2 * math.pi * new_h / 24) * math.sin(2 * math.pi * stored_h / 24)
            + math.cos(2 * math.pi * new_h / 24) * math.cos(2 * math.pi * stored_h / 24)
        )
        diurnal = (1.0 + cos_sim) / 2.0
        temporal_factor = _clamp(age_factor * diurnal)
        return 0.5 + 0.5 * temporal_factor

    # --- Composite score ---

    def _score_pair(
        self,
        new_frag: AbeyanceFragmentORM,
        stored_frag: AbeyanceFragmentORM,
        new_entities: set[str],
        stored_entities: set[str],
    ) -> list[dict]:
        """Score pair under compatible profiles with mask-aware redistribution."""
        new_modes = self._extract_failure_modes(new_frag)
        stored_modes = self._extract_failure_modes(stored_frag)
        compatible = new_modes & stored_modes
        if not compatible:
            compatible = set(WEIGHT_PROFILES_V3.keys())

        available = self._available_dimensions(new_frag, stored_frag)
        per_dim = self._compute_per_dimension_scores(
            new_frag, stored_frag, new_entities, stored_entities, available,
        )

        temporal_mod = self._compute_temporal_modifier(
            new_frag.event_timestamp, stored_frag.event_timestamp,
            stored_frag.source_type or "ALARM",
        )

        results = []
        for mode in compatible:
            base_w = self._get_weights(mode)
            adj_w = self._redistribute_weights(base_w, available)

            # Weighted combination (LLD §3.6)
            raw_composite = 0.0
            dim_map = {
                "semantic": "w_sem", "topological": "w_topo", "temporal": "w_temp",
                "operational": "w_oper", "entity_overlap": "w_ent",
            }
            for dim, key in dim_map.items():
                score = per_dim[dim]
                if score is not None and adj_w[key] > 0:
                    raw_composite += adj_w[key] * score

            final_score = _clamp(raw_composite * temporal_mod)
            # Round to 6 decimal places at persistence boundary
            final_score = round(final_score, 6)

            masks_active = {d: v for d, v in available.items()}

            results.append({
                "failure_mode_profile": mode,
                "score_semantic": per_dim["semantic"],
                "score_topological": per_dim["topological"],
                "score_temporal": per_dim["temporal"],
                "score_operational": per_dim["operational"],
                "score_entity_overlap": per_dim["entity_overlap"],
                "masks_active": masks_active,
                "weights_base": base_w,
                "weights_used": adj_w,
                "raw_composite": round(raw_composite, 6),
                "temporal_modifier": round(temporal_mod, 6),
                "final_score": final_score,
            })

        return results

    def _extract_failure_modes(self, frag: AbeyanceFragmentORM) -> set[str]:
        modes = set()
        for tag in (frag.failure_mode_tags or []):
            if isinstance(tag, dict):
                modes.add(tag.get("divergence_type", ""))
            elif isinstance(tag, str):
                modes.add(tag)
        return modes & set(WEIGHT_PROFILES_V3.keys())

    # --- Targeted retrieval ---

    async def _targeted_retrieval(
        self, session: AsyncSession, tenant_id: str, entity_ids: set[str],
        min_decay_score: float = 0.1,
    ) -> list[AbeyanceFragmentORM]:
        if not entity_ids:
            return []
        entity_stmt = (
            select(FragmentEntityRefORM.fragment_id)
            .where(
                FragmentEntityRefORM.tenant_id == tenant_id,
                FragmentEntityRefORM.entity_identifier.in_(list(entity_ids)),
            )
            .distinct()
        )
        entity_result = await session.execute(entity_stmt)
        fragment_ids = {row[0] for row in entity_result.fetchall()}
        if not fragment_ids:
            return []

        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.snap_status.in_(["ACTIVE", "NEAR_MISS"]),
                AbeyanceFragmentORM.current_decay_score >= min_decay_score,
                AbeyanceFragmentORM.id.in_(fragment_ids),
            )
            .order_by(AbeyanceFragmentORM.current_decay_score.desc())
            .limit(MAX_CANDIDATES)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # --- Full evaluation ---

    async def evaluate(
        self, session: AsyncSession, new_fragment: AbeyanceFragmentORM, tenant_id: str,
    ) -> dict:
        """Full v3 snap evaluation with mask-aware scoring."""
        entity_stmt = (
            select(FragmentEntityRefORM.entity_identifier)
            .where(
                FragmentEntityRefORM.fragment_id == new_fragment.id,
                FragmentEntityRefORM.tenant_id == tenant_id,
            )
        )
        entity_result = await session.execute(entity_stmt)
        new_entities = {row[0] for row in entity_result.fetchall()}

        candidates = await self._targeted_retrieval(session, tenant_id, new_entities)
        snaps, near_misses, affinities = [], [], []

        for candidate in candidates:
            if candidate.id == new_fragment.id:
                continue

            stored_stmt = (
                select(FragmentEntityRefORM.entity_identifier)
                .where(
                    FragmentEntityRefORM.fragment_id == candidate.id,
                    FragmentEntityRefORM.tenant_id == tenant_id,
                )
            )
            stored_result = await session.execute(stored_stmt)
            stored_entities = {row[0] for row in stored_result.fetchall()}

            profile_results = self._score_pair(new_fragment, candidate, new_entities, stored_entities)
            k = len(profile_results)
            snap_thresh = _sidak_threshold(BASE_SNAP_THRESHOLD, k)
            nm_thresh = _sidak_threshold(NEAR_MISS_THRESHOLD, k)
            aff_thresh = _sidak_threshold(AFFINITY_THRESHOLD, k)

            best_mode, best_score, best_decision = None, 0.0, "NONE"

            for pr in profile_results:
                score = pr["final_score"]
                decision = "NONE"
                if score >= snap_thresh:
                    decision = "SNAP"
                elif score >= nm_thresh:
                    decision = "NEAR_MISS"
                elif score >= aff_thresh:
                    decision = "AFFINITY"

                # Persist snap decision record (INV-10, INV-14)
                sdr = SnapDecisionRecordORM(
                    tenant_id=tenant_id,
                    new_fragment_id=new_fragment.id,
                    candidate_fragment_id=candidate.id,
                    failure_mode_profile=pr["failure_mode_profile"],
                    score_semantic=pr["score_semantic"],
                    score_topological=pr["score_topological"],
                    score_temporal=pr["score_temporal"],
                    score_operational=pr["score_operational"],
                    score_entity_overlap=pr["score_entity_overlap"],
                    masks_active=pr["masks_active"],
                    weights_used=pr["weights_used"],
                    weights_base=pr["weights_base"],
                    raw_composite=pr["raw_composite"],
                    temporal_modifier=pr["temporal_modifier"],
                    final_score=score,
                    threshold_applied=snap_thresh,
                    decision=decision,
                    multiple_comparisons_k=k,
                )
                session.add(sdr)

                if score > best_score:
                    best_score = score
                    best_mode = pr["failure_mode_profile"]
                    best_decision = decision

            if best_decision == "SNAP":
                snaps.append({"fragment_id": candidate.id, "score": best_score, "failure_mode": best_mode})
                await self._apply_snap(session, new_fragment, candidate, best_score, best_mode or "", tenant_id)
            elif best_decision == "NEAR_MISS":
                near_misses.append({"fragment_id": candidate.id, "score": best_score, "failure_mode": best_mode})
            elif best_decision == "AFFINITY":
                affinities.append({"fragment_id": candidate.id, "score": best_score, "failure_mode": best_mode})

        await session.flush()
        return {"snaps": snaps, "near_misses": near_misses, "affinities": affinities, "candidates_evaluated": len(candidates)}

    async def _apply_snap(
        self, session: AsyncSession,
        new_frag: AbeyanceFragmentORM, stored_frag: AbeyanceFragmentORM,
        score: float, failure_mode: str, tenant_id: str,
    ) -> None:
        from uuid import uuid4
        hypothesis_id = uuid4()

        for frag in [new_frag, stored_frag]:
            old_status = frag.snap_status
            valid_from = VALID_TRANSITIONS.get(old_status, set())
            if "SNAPPED" in valid_from or old_status in ("INGESTED", "ACTIVE", "NEAR_MISS"):
                frag.snap_status = "SNAPPED"
                frag.snapped_hypothesis_id = hypothesis_id
                frag.updated_at = datetime.now(timezone.utc)

                await self._provenance.log_state_change(
                    session,
                    FragmentStateChange(
                        fragment_id=frag.id,
                        tenant_id=tenant_id,
                        event_type="SNAPPED",
                        old_state={"status": old_status},
                        new_state={"status": "SNAPPED", "hypothesis_id": str(hypothesis_id)},
                        event_detail={
                            "snap_score": round(score, 6),
                            "failure_mode": failure_mode,
                            "partner_fragment_id": str(stored_frag.id if frag is new_frag else new_frag.id),
                        },
                    ),
                )

        await self._notifier.notify_snap(tenant_id, new_frag.id, hypothesis_id, score, failure_mode)
