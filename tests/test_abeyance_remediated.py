"""Tests for remediated Abeyance Memory subsystem.

Covers the post-Forensic-Audit implementations:
- DecayEngine (bounded boost, monotonicity, lifetime enforcement)
- SnapEngine scoring (Sidak correction, clamped temporal modifier)
- AccumulationGraph (LME scoring, correlation discount, union-find)
- EnrichmentChain (entity extraction, dedup key, content bounds)
- Events (ProvenanceLogger, RedisNotifier write-ahead pattern)
- State machine (VALID_TRANSITIONS, INV-1)
- MaintenanceService (bounded batches)

All tests use mocks — no database or network required.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import numpy as np
import pytest

from backend.app.models.abeyance_orm import (
    VALID_TRANSITIONS,
    MAX_RAW_CONTENT_BYTES,
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
)


# ---------------------------------------------------------------------------
# INV-1: State Machine
# ---------------------------------------------------------------------------

class TestStateMachine:
    """Verify the deterministic fragment lifecycle (INV-1)."""

    def test_ingested_can_only_transition_to_active(self):
        assert VALID_TRANSITIONS["INGESTED"] == {"ACTIVE"}

    def test_active_transitions(self):
        assert VALID_TRANSITIONS["ACTIVE"] == {"NEAR_MISS", "SNAPPED", "STALE"}

    def test_near_miss_transitions(self):
        assert VALID_TRANSITIONS["NEAR_MISS"] == {"SNAPPED", "ACTIVE", "STALE"}

    def test_snapped_is_terminal(self):
        """INV-5: SNAPPED has no automated exit."""
        assert VALID_TRANSITIONS["SNAPPED"] == set()

    def test_cold_is_terminal(self):
        assert VALID_TRANSITIONS["COLD"] == set()

    def test_stale_can_only_expire(self):
        assert VALID_TRANSITIONS["STALE"] == {"EXPIRED"}

    def test_expired_can_only_go_cold(self):
        assert VALID_TRANSITIONS["EXPIRED"] == {"COLD"}

    def test_all_states_are_defined(self):
        expected_states = {"INGESTED", "ACTIVE", "NEAR_MISS", "SNAPPED", "STALE", "EXPIRED", "COLD"}
        assert set(VALID_TRANSITIONS.keys()) == expected_states


# ---------------------------------------------------------------------------
# INV-6: Content bounds
# ---------------------------------------------------------------------------

class TestContentBounds:
    def test_max_raw_content_bytes_is_64kb(self):
        assert MAX_RAW_CONTENT_BYTES == 65536


# ---------------------------------------------------------------------------
# DecayEngine
# ---------------------------------------------------------------------------

class TestDecayEngine:
    """Tests for the remediated DecayEngine."""

    def setup_method(self):
        from backend.app.services.abeyance.decay_engine import DecayEngine
        from backend.app.services.abeyance.events import ProvenanceLogger, RedisNotifier
        self.provenance = ProvenanceLogger()
        self.notifier = RedisNotifier(redis_client=None)
        self.engine = DecayEngine(provenance=self.provenance, notifier=self.notifier)

    def test_compute_decay_score_new_fragment(self):
        """Brand-new fragment has score = base_relevance."""
        from backend.app.services.abeyance.decay_engine import DecayEngine
        score = DecayEngine.compute_decay_score(
            base_relevance=0.9, near_miss_count=0,
            age_days=0.0, source_type="ALARM",
        )
        assert score == pytest.approx(0.9, abs=1e-9)

    def test_compute_decay_score_after_90_days_with_tau_90(self):
        """After 1 time-constant (ALARM tau=90), score = base * e^(-1)."""
        from backend.app.services.abeyance.decay_engine import DecayEngine
        score = DecayEngine.compute_decay_score(
            base_relevance=0.9, near_miss_count=0,
            age_days=90.0, source_type="ALARM",
        )
        expected = 0.9 * math.exp(-1.0)
        assert score == pytest.approx(expected, rel=1e-6)

    def test_near_miss_boost_is_bounded(self):
        """Boost factor = 1 + min(n, 10) * 0.05, capped at 1.5 (Audit §2.2 fix)."""
        from backend.app.services.abeyance.decay_engine import DecayEngine
        score_no_boost = DecayEngine.compute_decay_score(
            base_relevance=0.9, near_miss_count=0,
            age_days=30.0, source_type="ALARM",
        )
        score_max_boost = DecayEngine.compute_decay_score(
            base_relevance=0.9, near_miss_count=100,  # Should cap at 10
            age_days=30.0, source_type="ALARM",
        )
        # Max boost factor = 1 + min(100,10)*0.05 = 1.5
        assert score_max_boost == pytest.approx(score_no_boost * 1.5, rel=1e-6)

    def test_compute_decay_score_clamped_to_unit_interval(self):
        """Output always in [0.0, 1.0]."""
        from backend.app.services.abeyance.decay_engine import DecayEngine
        score = DecayEngine.compute_decay_score(
            base_relevance=1.0, near_miss_count=10,
            age_days=0.0, source_type="ALARM",
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Snap Engine Scoring
# ---------------------------------------------------------------------------

class TestSnapScoring:
    """Tests for Sidak correction and temporal modifier clamping."""

    def test_sidak_threshold_k1_returns_base(self):
        from backend.app.services.abeyance.snap_engine import _sidak_threshold
        assert _sidak_threshold(0.75, 1) == 0.75

    def test_sidak_threshold_k5(self):
        """Sidak at k=5, base=0.75: 1 - (1-0.75)^(1/5) = 1 - 0.25^0.2 ≈ 0.113."""
        from backend.app.services.abeyance.snap_engine import _sidak_threshold
        result = _sidak_threshold(0.75, 5)
        expected = 1.0 - (0.25 ** 0.2)
        assert result == pytest.approx(expected, rel=1e-6)
        # Threshold gets STRICTER (lower) with more comparisons
        assert result < 0.75

    def test_sidak_threshold_increases_with_k(self):
        """More comparisons means stricter (lower) corrected threshold."""
        from backend.app.services.abeyance.snap_engine import _sidak_threshold
        t1 = _sidak_threshold(0.75, 1)
        t5 = _sidak_threshold(0.75, 5)
        t20 = _sidak_threshold(0.75, 20)
        assert t1 > t5 > t20

    def test_temporal_modifier_no_timestamps_returns_075(self):
        """Missing timestamps default to 0.75 (neutral-ish attenuation)."""
        from backend.app.services.abeyance.snap_engine import SnapEngine
        from backend.app.services.abeyance.events import ProvenanceLogger
        engine = SnapEngine(provenance=ProvenanceLogger())
        result = engine._compute_temporal_modifier(
            new_time=None, stored_time=None,
            new_fp={}, stored_fp={}, source_type="ALARM",
        )
        assert result == 0.75

    def test_temporal_modifier_bounded_05_to_10(self):
        """Temporal modifier cannot amplify: range is [0.5, 1.0] (Audit §4.2 fix)."""
        from backend.app.services.abeyance.snap_engine import SnapEngine
        from backend.app.services.abeyance.events import ProvenanceLogger
        engine = SnapEngine(provenance=ProvenanceLogger())
        now = datetime.now(timezone.utc)
        # Very close in time (should push towards 1.0)
        result_close = engine._compute_temporal_modifier(
            new_time=now, stored_time=now - timedelta(hours=1),
            new_fp={}, stored_fp={}, source_type="ALARM",
        )
        # Very far apart (should push towards 0.5)
        result_far = engine._compute_temporal_modifier(
            new_time=now, stored_time=now - timedelta(days=365),
            new_fp={}, stored_fp={}, source_type="ALARM",
        )
        assert 0.5 <= result_close <= 1.0
        assert 0.5 <= result_far <= 1.0


# ---------------------------------------------------------------------------
# Accumulation Graph: LME Scoring
# ---------------------------------------------------------------------------

class TestLMEScoring:
    """Tests for Log-Mean-Exp replacing Noisy-OR (Audit §4.1 fix)."""

    def test_lme_empty_scores_returns_zero(self):
        from backend.app.services.abeyance.accumulation_graph import _log_mean_exp
        assert _log_mean_exp([]) == 0.0

    def test_lme_single_score(self):
        from backend.app.services.abeyance.accumulation_graph import _log_mean_exp
        result = _log_mean_exp([0.6])
        assert result == pytest.approx(0.6, rel=1e-3)

    def test_lme_bounded_by_input_range(self):
        """LME output must be within [min(inputs), max(inputs)]."""
        from backend.app.services.abeyance.accumulation_graph import _log_mean_exp
        scores = [0.38, 0.42, 0.45, 0.48, 0.50]
        result = _log_mean_exp(scores)
        assert min(scores) <= result <= max(scores)

    def test_lme_vs_noisy_or_five_weak_signals(self):
        """LLD verification: 5 edges [0.50, 0.45, 0.42, 0.48, 0.38].

        Noisy-OR would give 0.949 (overconfident).
        LME should give a score much lower than Noisy-OR.
        """
        from backend.app.services.abeyance.accumulation_graph import _log_mean_exp
        scores = [0.50, 0.45, 0.42, 0.48, 0.38]
        lme = _log_mean_exp(scores)
        noisy_or = 1.0 - math.prod(1.0 - s for s in scores)
        # LME must be dramatically lower than Noisy-OR
        assert lme < noisy_or, "LME should be lower than Noisy-OR"
        # LME should be bounded by input range
        assert min(scores) <= lme <= max(scores)

    def test_lme_five_strong_signals(self):
        """5 strong signals [0.90, 0.88, 0.85, 0.92, 0.87] — LME should be high but < 1.0."""
        from backend.app.services.abeyance.accumulation_graph import _log_mean_exp
        scores = [0.90, 0.88, 0.85, 0.92, 0.87]
        result = _log_mean_exp(scores)
        assert result > 0.5  # Strong signals should give meaningful score
        assert result <= 1.0

    def test_correlation_discount_low_density(self):
        """Low density (few edges relative to max) should not discount much."""
        from backend.app.services.abeyance.accumulation_graph import _correlation_discount
        # 3 nodes, 2 edges (sparse): density = 2/3 = 0.667
        discount = _correlation_discount(num_nodes=3, num_edges=2)
        assert 0.5 <= discount <= 1.0

    def test_correlation_discount_high_density(self):
        """Very dense cluster should be discounted more."""
        from backend.app.services.abeyance.accumulation_graph import _correlation_discount
        # 5 nodes, 10 edges (max): density = 10/10 = 1.0
        discount = _correlation_discount(num_nodes=5, num_edges=10)
        assert discount < 1.0
        assert discount >= 0.5


# ---------------------------------------------------------------------------
# Events: ProvenanceLogger + RedisNotifier
# ---------------------------------------------------------------------------

class TestEvents:
    """Tests for the write-ahead logging pattern (INV-12)."""

    @pytest.mark.asyncio
    async def test_provenance_logger_writes_to_session(self):
        """ProvenanceLogger persists to DB (step 1 of write-ahead)."""
        from backend.app.services.abeyance.events import ProvenanceLogger, FragmentStateChange
        prov = ProvenanceLogger()
        session = AsyncMock()

        change = FragmentStateChange(
            fragment_id=uuid4(),
            tenant_id="test-tenant",
            event_type="SNAPPED",
            old_state={"status": "ACTIVE"},
            new_state={"status": "SNAPPED"},
        )
        await prov.log_state_change(session, change)
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_notifier_survives_no_client(self):
        """RedisNotifier with no Redis client logs warning but doesn't raise."""
        from backend.app.services.abeyance.events import RedisNotifier
        notifier = RedisNotifier(redis_client=None)
        # notify_snap should not raise when Redis is unavailable
        result = await notifier.notify_snap(
            tenant_id="test", fragment_id=uuid4(),
            hypothesis_id=uuid4(), score=0.8, failure_mode="DARK_EDGE",
        )
        assert result is False  # Notification skipped

    @pytest.mark.asyncio
    async def test_redis_notifier_survives_broken_client(self):
        """RedisNotifier catches errors from a failing Redis client."""
        from backend.app.services.abeyance.events import RedisNotifier
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=Exception("connection refused"))
        notifier = RedisNotifier(redis_client=mock_redis)
        # Should not raise even with broken client
        result = await notifier.notify_snap(
            tenant_id="test", fragment_id=uuid4(),
            hypothesis_id=uuid4(), score=0.8, failure_mode="DARK_EDGE",
        )
        assert result is False


# ---------------------------------------------------------------------------
# Enrichment Chain: Dedup + Entity Extraction
# ---------------------------------------------------------------------------

class TestEnrichmentHelpers:
    """Test enrichment chain utility methods."""

    def test_dedup_key_is_deterministic(self):
        """Same inputs produce same dedup_key."""
        from backend.app.services.abeyance.enrichment_chain import EnrichmentChain
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChain(provenance=ProvenanceLogger())
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)

        key1 = chain._compute_dedup_key("tenant-1", "ALARM", "REF-001", ts)
        key2 = chain._compute_dedup_key("tenant-1", "ALARM", "REF-001", ts)
        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex

    def test_dedup_key_differs_for_different_inputs(self):
        from backend.app.services.abeyance.enrichment_chain import EnrichmentChain
        from backend.app.services.abeyance.events import ProvenanceLogger
        chain = EnrichmentChain(provenance=ProvenanceLogger())
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)

        key1 = chain._compute_dedup_key("tenant-1", "ALARM", "REF-001", ts)
        key2 = chain._compute_dedup_key("tenant-1", "ALARM", "REF-002", ts)
        assert key1 != key2

    def test_entity_pattern_matches_ran(self):
        """Regex pattern matches LTE/NR station identifiers."""
        from backend.app.services.abeyance.enrichment_chain import ENTITY_PATTERNS
        import re
        ran_patterns = [(p, d) for p, d in ENTITY_PATTERNS if d == "RAN"]
        assert len(ran_patterns) > 0
        # Should match something like LTE-SITE-A01
        found = False
        for pattern, domain in ran_patterns:
            if re.search(pattern, "Cell LTE-NORTH-A01 reported anomaly"):
                found = True
                break
        assert found, "RAN patterns should match LTE station identifiers"


# ---------------------------------------------------------------------------
# ORM model defaults
# ---------------------------------------------------------------------------

class TestORMDefaults:
    """Verify ORM model column definitions from remediation."""

    def test_fragment_snap_status_column_default_is_ingested(self):
        """The snap_status column default is 'INGESTED' (not 'ABEYANCE')."""
        col = AbeyanceFragmentORM.__table__.c.snap_status
        assert col.default.arg == "INGESTED"

    def test_fragment_max_lifetime_column_default(self):
        col = AbeyanceFragmentORM.__table__.c.max_lifetime_days
        assert col.default.arg == 730

    def test_fragment_base_relevance_column_default(self):
        col = AbeyanceFragmentORM.__table__.c.base_relevance
        assert col.default.arg == 1.0

    def test_fragment_near_miss_count_column_default(self):
        col = AbeyanceFragmentORM.__table__.c.near_miss_count
        assert col.default.arg == 0

    def test_fragment_has_embedding_mask_column(self):
        """embedding_mask column exists on the fragment table."""
        assert "embedding_mask" in AbeyanceFragmentORM.__table__.c

    def test_fragment_has_dedup_key_column(self):
        """dedup_key column exists for deduplication (Phase 7)."""
        assert "dedup_key" in AbeyanceFragmentORM.__table__.c


# ---------------------------------------------------------------------------
# MaintenanceService
# ---------------------------------------------------------------------------

class TestMaintenanceBounds:
    """Verify maintenance batch size constants."""

    def test_batch_size_constants_are_reasonable(self):
        from backend.app.services.abeyance.maintenance import (
            MAX_DECAY_BATCH, MAX_ARCHIVE_BATCH, MAX_PRUNE_BATCH,
        )
        assert MAX_DECAY_BATCH == 10_000
        assert MAX_ARCHIVE_BATCH == 5_000
        assert MAX_PRUNE_BATCH == 10_000


# ---------------------------------------------------------------------------
# Shadow Topology BFS Bounds
# ---------------------------------------------------------------------------

class TestShadowTopologyBounds:
    def test_max_bfs_result_is_bounded(self):
        from backend.app.services.abeyance.shadow_topology import MAX_BFS_RESULT, MAX_HOPS
        assert MAX_BFS_RESULT == 500
        assert MAX_HOPS == 3


# ---------------------------------------------------------------------------
# Accumulation Graph Bounds
# ---------------------------------------------------------------------------

class TestAccumulationGraphBounds:
    def test_edge_limit_per_fragment(self):
        from backend.app.services.abeyance.accumulation_graph import (
            MAX_EDGES_PER_FRAGMENT, MIN_CLUSTER_SIZE, MAX_CLUSTER_SIZE,
        )
        assert MAX_EDGES_PER_FRAGMENT == 20
        assert MIN_CLUSTER_SIZE == 3
        assert MAX_CLUSTER_SIZE == 50


# ---------------------------------------------------------------------------
# Snap Engine Weight Profiles
# ---------------------------------------------------------------------------

class TestWeightProfiles:
    """All weight profiles must sum to 1.0."""

    def test_all_weight_profiles_sum_to_one(self):
        from backend.app.services.abeyance.snap_engine import WEIGHT_PROFILES
        for mode, weights in WEIGHT_PROFILES.items():
            total = sum(weights.values())
            assert total == pytest.approx(1.0, abs=1e-9), (
                f"Weight profile {mode} sums to {total}, expected 1.0"
            )

    def test_all_weights_are_positive(self):
        from backend.app.services.abeyance.snap_engine import WEIGHT_PROFILES
        for mode, weights in WEIGHT_PROFILES.items():
            for key, val in weights.items():
                assert val > 0, f"{mode}.{key} = {val} must be positive"


# ---------------------------------------------------------------------------
# Service Factory
# ---------------------------------------------------------------------------

class TestServiceFactory:
    """Verify create_abeyance_services returns all required services."""

    def test_factory_returns_all_services(self):
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        # v2 core keys (backward compat)
        v2_keys = {
            "provenance", "notifier", "enrichment", "snap_engine",
            "accumulation_graph", "decay_engine", "shadow_topology",
            "value_attribution", "incident_reconstruction", "maintenance",
        }
        # v3 keys
        v3_keys = {
            "tvec", "tslam", "enrichment_v3", "snap_engine_v3",
            "discovery_loop",
        }
        # discovery mechanism keys
        mechanism_keys = {
            "surprise_engine", "ignorance_mapper", "negative_evidence",
            "bridge_detector", "outcome_calibration", "pattern_conflict",
            "temporal_sequence", "hypothesis_generator", "expectation_violation",
            "causal_direction", "pattern_compressor", "counterfactual_sim",
            "meta_memory", "evolutionary_patterns",
        }
        expected_keys = v2_keys | v3_keys | mechanism_keys
        assert set(services.keys()) == expected_keys

    def test_services_share_provenance(self):
        from backend.app.services.abeyance import create_abeyance_services
        services = create_abeyance_services()
        # Snap engine and decay engine should share the same provenance logger
        assert services["snap_engine"]._provenance is services["decay_engine"]._provenance
