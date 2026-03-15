"""
Snap Engine — the heart of Abeyance Memory.

Implements ABEYANCE_MEMORY_LLD.md §9 (The Snap Engine).

Evaluates whether a newly arrived fragment connects to one or more stored
fragments to form a Dark Graph hypothesis. Runs in three stages:
  Stage 1: Targeted Retrieval (§9 Stage 1)
  Stage 2: Evidence Scoring (§9 Stage 2)
  Stage 3: Snap Decision (§9 Stage 3)
"""

import math
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import numpy as np
from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
)
from backend.app.schemas.abeyance import (
    ScoredPair,
    SnapResult,
    SOURCE_TYPE_DEFAULTS,
)
from backend.app.services.abeyance.shadow_topology import ShadowTopologyService
from backend.app.services.event_bus import EventBus

logger = get_logger(__name__)


class SnapEngine:
    """The 3-stage snap evaluation engine (LLD §9).

    Detects when new evidence activates dormant fragments by comparing
    incoming fragments against stored fragments using multi-dimensional
    scoring weighted by failure mode profiles.
    """

    # Snap thresholds (LLD §9 Stage 3)
    SNAP_THRESHOLD = 0.75
    NEAR_MISS_THRESHOLD = 0.55
    AFFINITY_THRESHOLD = 0.40
    RELEVANCE_BOOST = 1.15

    # Weight profiles by failure mode (LLD §9 Stage 2)
    WEIGHT_PROFILES: dict[str, dict[str, float]] = {
        "DARK_EDGE":         {"w_sem": 0.20, "w_topo": 0.35, "w_entity": 0.25, "w_oper": 0.20},
        "DARK_NODE":         {"w_sem": 0.30, "w_topo": 0.15, "w_entity": 0.35, "w_oper": 0.20},
        "IDENTITY_MUTATION": {"w_sem": 0.15, "w_topo": 0.20, "w_entity": 0.45, "w_oper": 0.20},
        "PHANTOM_CI":        {"w_sem": 0.25, "w_topo": 0.20, "w_entity": 0.30, "w_oper": 0.25},
        "DARK_ATTRIBUTE":    {"w_sem": 0.30, "w_topo": 0.15, "w_entity": 0.25, "w_oper": 0.30},
    }

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        shadow_topology: ShadowTopologyService,
        event_bus: EventBus,
        accumulation_graph: Any = None,
    ):
        self.session_factory = session_factory
        self.shadow_topology = shadow_topology
        self.event_bus = event_bus
        self.accumulation_graph = accumulation_graph

    async def evaluate(
        self,
        new_fragment: AbeyanceFragmentORM,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> SnapResult:
        """Execute the 3-stage snap evaluation (LLD §9).

        Returns SnapResult with lists of snaps, near-misses, and affinities.
        """
        async with self._get_session(session) as s:
            # Stage 1: Targeted Retrieval (LLD §9 Stage 1)
            candidates = await self._targeted_retrieval(new_fragment, tenant_id, s)

            if not candidates:
                return SnapResult()

            # Get entity identifiers for the new fragment
            new_entity_ids = self._extract_entity_identifiers(new_fragment)
            new_failure_modes = self._extract_failure_modes(new_fragment)

            # Stage 2: Evidence Scoring (LLD §9 Stage 2)
            scored_pairs: list[ScoredPair] = []
            for candidate in candidates:
                best_score, best_mode = await self._score_pair(
                    new_fragment, candidate, new_entity_ids, tenant_id, s
                )
                if best_score > 0:
                    scored_pairs.append(ScoredPair(
                        stored_fragment_id=candidate.id,
                        score=best_score,
                        failure_mode=best_mode or "DARK_EDGE",
                    ))

            # Stage 3: Snap Decision (LLD §9 Stage 3)
            snaps = []
            near_misses = []
            affinities = []

            for pair in scored_pairs:
                if pair.score >= self.SNAP_THRESHOLD:
                    snaps.append(pair)
                elif pair.score >= self.NEAR_MISS_THRESHOLD:
                    near_misses.append(pair)
                    affinities.append(pair)
                elif pair.score >= self.AFFINITY_THRESHOLD:
                    affinities.append(pair)

            # Process snaps — update fragment status
            for snap in snaps:
                await self._process_snap(new_fragment, snap, tenant_id, s)

            # Process near-misses — boost relevance (LLD §9)
            for nm in near_misses:
                await self._boost_relevance(nm.stored_fragment_id, s)

            # Process affinities — create accumulation edges
            if self.accumulation_graph and affinities:
                for aff in affinities:
                    await self.accumulation_graph.add_or_update_edge(
                        tenant_id=tenant_id,
                        fragment_a_id=new_fragment.id,
                        fragment_b_id=aff.stored_fragment_id,
                        affinity_score=aff.score,
                        failure_mode=aff.failure_mode,
                        session=s,
                    )
                # Evaluate clusters after adding new edges
                await self.accumulation_graph.evaluate_clusters(
                    tenant_id=tenant_id,
                    trigger_fragment_id=new_fragment.id,
                    session=s,
                )

            result = SnapResult(
                snaps=snaps,
                near_misses=near_misses,
                affinities=affinities,
            )

            logger.info(
                f"Snap evaluation: fragment={new_fragment.id}, "
                f"candidates={len(candidates)}, snaps={len(snaps)}, "
                f"near_misses={len(near_misses)}, affinities={len(affinities)}"
            )
            return result

    async def _targeted_retrieval(
        self,
        fragment: AbeyanceFragmentORM,
        tenant_id: str,
        session: AsyncSession,
    ) -> list[AbeyanceFragmentORM]:
        """Stage 1: Targeted Retrieval (LLD §9 Stage 1).

        Reduces the candidate set using entity overlap and failure mode
        compatibility. Uses structured query, not vector scan.
        """
        entity_identifiers = self._extract_entity_identifiers(fragment)
        failure_modes = self._extract_failure_modes(fragment)

        if not entity_identifiers and not failure_modes:
            return []

        # Query fragments with entity overlap via fragment_entity_ref
        sql = text("""
            SELECT DISTINCT af.*
            FROM abeyance_fragment af
            LEFT JOIN fragment_entity_ref fer ON af.id = fer.fragment_id
            WHERE af.tenant_id = :tenant_id
              AND af.snap_status = 'ABEYANCE'
              AND af.current_decay_score > 0.1
              AND af.id != :fragment_id
              AND (
                  fer.entity_identifier = ANY(:entity_ids)
                  OR af.failure_mode_tags @> ANY(ARRAY[:failure_modes]::jsonb[])
              )
            ORDER BY af.current_decay_score DESC
            LIMIT 200
        """)

        # Simpler fallback query using just entity overlap
        simple_sql = text("""
            SELECT DISTINCT af.*
            FROM abeyance_fragment af
            JOIN fragment_entity_ref fer ON af.id = fer.fragment_id
            WHERE af.tenant_id = :tenant_id
              AND af.snap_status = 'ABEYANCE'
              AND af.current_decay_score > 0.1
              AND af.id != :fragment_id
              AND fer.entity_identifier = ANY(:entity_ids)
            ORDER BY af.current_decay_score DESC
            LIMIT 200
        """)

        try:
            result = await session.execute(
                simple_sql,
                {
                    "tenant_id": tenant_id,
                    "fragment_id": str(fragment.id),
                    "entity_ids": entity_identifiers or ["__none__"],
                },
            )
            rows = result.fetchall()
            # Convert rows to ORM objects
            candidates = []
            for row in rows:
                candidate = await session.get(AbeyanceFragmentORM, row.id)
                if candidate:
                    candidates.append(candidate)
            return candidates
        except Exception as e:
            logger.warning(f"Targeted retrieval query failed: {e}")
            # Fallback: query by tenant only
            result = await session.execute(
                select(AbeyanceFragmentORM).where(
                    AbeyanceFragmentORM.tenant_id == tenant_id,
                    AbeyanceFragmentORM.snap_status == "ABEYANCE",
                    AbeyanceFragmentORM.current_decay_score > 0.1,
                    AbeyanceFragmentORM.id != fragment.id,
                ).order_by(
                    AbeyanceFragmentORM.current_decay_score.desc()
                ).limit(200)
            )
            return list(result.scalars().all())

    async def _score_pair(
        self,
        new_frag: AbeyanceFragmentORM,
        stored_frag: AbeyanceFragmentORM,
        new_entity_ids: list[str],
        tenant_id: str,
        session: AsyncSession,
    ) -> tuple[float, Optional[str]]:
        """Score a candidate pair under each compatible failure mode (LLD §9 Stage 2).

        Returns the best score and corresponding failure mode.
        """
        compatible_modes = self._compatible_modes(new_frag, stored_frag)
        stored_entity_ids = self._extract_entity_identifiers(stored_frag)

        best_score = 0.0
        best_mode = None

        for mode in compatible_modes:
            w = self.WEIGHT_PROFILES.get(mode, self.WEIGHT_PROFILES["DARK_EDGE"])

            # Semantic similarity (cosine of enriched embeddings)
            semantic_sim = self._cosine_similarity(
                new_frag.enriched_embedding, stored_frag.enriched_embedding
            )

            # Topological proximity via Shadow Topology
            topo_prox = await self.shadow_topology.topological_proximity(
                tenant_id=tenant_id,
                entity_set_a=set(new_entity_ids),
                entity_set_b=set(stored_entity_ids),
                session=session,
            )

            # Entity overlap (Jaccard similarity)
            entity_overlap = self._jaccard_similarity(
                set(new_entity_ids), set(stored_entity_ids)
            )

            # Operational context similarity
            oper_sim = self._operational_similarity(
                new_frag.operational_fingerprint or {},
                stored_frag.operational_fingerprint or {},
            )

            # Temporal weight (LLD §9)
            temp_weight = self._temporal_weight(new_frag, stored_frag)

            # Weighted score (LLD §9 formula)
            score = (
                w["w_sem"] * semantic_sim
                + w["w_topo"] * topo_prox
                + w["w_entity"] * entity_overlap
                + w["w_oper"] * oper_sim
            ) * temp_weight

            if score > best_score:
                best_score = score
                best_mode = mode

        return best_score, best_mode

    def _temporal_weight(
        self,
        new_frag: AbeyanceFragmentORM,
        stored_frag: AbeyanceFragmentORM,
    ) -> float:
        """Context-aware temporal weighting (LLD §9).

        temporal_weight = exp(-age/τ) × (1 + γ × shared_change_proximity) × diurnal_alignment
        """
        now = datetime.now(timezone.utc)
        stored_time = stored_frag.event_timestamp or stored_frag.created_at or now
        if stored_time.tzinfo is None:
            stored_time = stored_time.replace(tzinfo=timezone.utc)

        age_days = (now - stored_time).total_seconds() / 86400.0

        # Source-type-dependent τ
        source_defaults = SOURCE_TYPE_DEFAULTS.get(
            stored_frag.source_type or "ALARM",
            {"decay_tau": 90.0},
        )
        tau = source_defaults.get("decay_tau", 90.0)

        # Base decay
        base_decay = math.exp(-age_days / tau)

        # Change proximity bonus (γ = 0.5 default)
        gamma = 0.5
        new_fp = new_frag.operational_fingerprint or {}
        stored_fp = stored_frag.operational_fingerprint or {}
        new_change_h = (new_fp.get("change_proximity") or {}).get("nearest_change_hours")
        stored_change_h = (stored_fp.get("change_proximity") or {}).get("nearest_change_hours")

        shared_change = 0.0
        if new_change_h is not None and stored_change_h is not None:
            # Both near a change window — bonus if they reference the same change
            if new_change_h < 72 and stored_change_h < 72:
                shared_change = 1.0

        # Diurnal alignment (cosine similarity of time-of-day encodings)
        new_ctx = new_frag.temporal_context or {}
        stored_ctx = stored_frag.temporal_context or {}
        diurnal = self._diurnal_alignment(new_ctx, stored_ctx)

        weight = base_decay * (1 + gamma * shared_change) * diurnal
        return max(0.01, min(2.0, weight))  # Clamp to reasonable range

    def _diurnal_alignment(self, ctx_a: dict, ctx_b: dict) -> float:
        """Cosine similarity of time-of-day sinusoidal encodings."""
        vec_a = [
            ctx_a.get("time_of_day_sin", 0),
            ctx_a.get("time_of_day_cos", 0),
            ctx_a.get("day_of_week_sin", 0),
            ctx_a.get("day_of_week_cos", 0),
        ]
        vec_b = [
            ctx_b.get("time_of_day_sin", 0),
            ctx_b.get("time_of_day_cos", 0),
            ctx_b.get("day_of_week_sin", 0),
            ctx_b.get("day_of_week_cos", 0),
        ]
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
        norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
        sim = dot / (norm_a * norm_b)
        # Map from [-1, 1] to [0.5, 1.5] — same time of day gets bonus
        return 0.5 + 0.5 * (sim + 1.0) / 2.0

    def _cosine_similarity(self, vec_a: Any, vec_b: Any) -> float:
        """Cosine similarity between two embedding vectors."""
        if vec_a is None or vec_b is None:
            return 0.0
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        if a.shape != b.shape or np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
            return 0.0
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def _jaccard_similarity(self, set_a: set, set_b: set) -> float:
        """Jaccard similarity of two sets."""
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _operational_similarity(self, fp_a: dict, fp_b: dict) -> float:
        """Cosine similarity of operational fingerprint feature vectors."""
        def _extract_features(fp: dict) -> list[float]:
            cp = fp.get("change_proximity", {})
            vu = fp.get("vendor_upgrade", {})
            tc = fp.get("traffic_cycle", {})
            ca = fp.get("concurrent_alarms", {})
            return [
                math.exp(-(cp.get("nearest_change_hours", 999) ** 2) / (2 * 24 ** 2)),
                math.exp(-((vu.get("days_since_upgrade") or 999) / 30.0)),
                tc.get("load_ratio_vs_baseline", 0.5),
                min(ca.get("count_1h_window", 0) / 10.0, 1.0),
            ]

        a = _extract_features(fp_a)
        b = _extract_features(fp_b)
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (norm_a * norm_b)

    def _compatible_modes(
        self,
        new_frag: AbeyanceFragmentORM,
        stored_frag: AbeyanceFragmentORM,
    ) -> list[str]:
        """Determine compatible failure modes for scoring (LLD §9 Stage 2)."""
        new_modes = self._extract_failure_modes(new_frag)
        stored_modes = self._extract_failure_modes(stored_frag)

        # Use intersection if both have modes, otherwise use all profiles
        if new_modes and stored_modes:
            compatible = list(set(new_modes) & set(stored_modes))
            if compatible:
                return compatible
            # If no overlap, evaluate under all modes from both
            return list(set(new_modes) | set(stored_modes))

        return list(self.WEIGHT_PROFILES.keys())

    def _extract_entity_identifiers(self, fragment: AbeyanceFragmentORM) -> list[str]:
        """Extract entity identifiers from fragment's extracted_entities JSONB."""
        entities = fragment.extracted_entities or []
        if isinstance(entities, list):
            return [
                e.get("entity_identifier", "") if isinstance(e, dict) else str(e)
                for e in entities
                if e
            ]
        return []

    def _extract_failure_modes(self, fragment: AbeyanceFragmentORM) -> list[str]:
        """Extract failure mode types from fragment's failure_mode_tags JSONB."""
        tags = fragment.failure_mode_tags or []
        if isinstance(tags, list):
            return [
                t.get("divergence_type", "") if isinstance(t, dict) else str(t)
                for t in tags
                if t
            ]
        return []

    async def _process_snap(
        self,
        new_fragment: AbeyanceFragmentORM,
        snap: ScoredPair,
        tenant_id: str,
        session: AsyncSession,
    ) -> None:
        """Process a successful snap — update fragments, emit event."""
        now = datetime.now(timezone.utc)

        # Update new fragment
        new_fragment.snap_status = "SNAPPED"
        new_fragment.snapped_hypothesis_id = snap.stored_fragment_id
        new_fragment.updated_at = now

        # Update stored fragment
        stored = await session.get(AbeyanceFragmentORM, snap.stored_fragment_id)
        if stored:
            stored.snap_status = "SNAPPED"
            stored.snapped_hypothesis_id = new_fragment.id
            stored.updated_at = now

        # Emit snap event (LLD §9)
        await self._emit_snap_event(
            tenant_id=tenant_id,
            fragment_a_id=new_fragment.id,
            fragment_b_id=snap.stored_fragment_id,
            score=snap.score,
            failure_mode=snap.failure_mode,
        )

    async def _boost_relevance(
        self,
        fragment_id: UUID,
        session: AsyncSession,
    ) -> None:
        """Boost a near-miss fragment's relevance by 1.15× (LLD §9 Stage 3)."""
        fragment = await session.get(AbeyanceFragmentORM, fragment_id)
        if fragment:
            fragment.base_relevance *= self.RELEVANCE_BOOST
            fragment.near_miss_count += 1
            fragment.updated_at = datetime.now(timezone.utc)

    async def _emit_snap_event(
        self,
        tenant_id: str,
        fragment_a_id: UUID,
        fragment_b_id: UUID,
        score: float,
        failure_mode: str,
    ) -> None:
        """Emit abeyance.snap_occurred event via Redis Streams (LLD §9)."""
        try:
            await self.event_bus.publish(
                event_type="abeyance.snap_occurred",
                payload={
                    "snap_id": str(fragment_a_id),
                    "evidence_fragment_id": str(fragment_a_id),
                    "matched_fragment_ids": [str(fragment_b_id)],
                    "confidence_score": score,
                    "failure_mode": failure_mode,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.error(f"Failed to emit snap event: {e}")

    def _get_session(self, session: Optional[AsyncSession] = None):
        """Support both external session (reuse) and internal session creation."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
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

        return _ctx()
