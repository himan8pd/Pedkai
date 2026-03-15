"""Tests for SnapEngine — the core fragment matching engine.

Tests the weight profile selection, scoring formula, threshold logic,
temporal weight computation, near-miss relevance boost, and event emission.

All tests operate on mocked objects — no live database required.

LLD ref: §9 (The Snap Engine)
"""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.abeyance.snap_engine import SnapEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fragment(
    fragment_id=None,
    tenant_id="test-tenant",
    source_type="ALARM",
    snap_status="ABEYANCE",
    enriched_embedding=None,
    extracted_entities=None,
    failure_mode_tags=None,
    operational_fingerprint=None,
    temporal_context=None,
    event_timestamp=None,
    created_at=None,
    base_relevance=0.8,
    current_decay_score=0.9,
    near_miss_count=0,
):
    frag = MagicMock()
    frag.id = fragment_id or uuid4()
    frag.tenant_id = tenant_id
    frag.source_type = source_type
    frag.snap_status = snap_status
    frag.enriched_embedding = enriched_embedding if enriched_embedding is not None else [0.1] * 1536
    frag.extracted_entities = extracted_entities if extracted_entities is not None else [
        {"entity_identifier": "LTE-001-A", "entity_domain": "RAN"},
    ]
    frag.failure_mode_tags = failure_mode_tags if failure_mode_tags is not None else [
        {"divergence_type": "DARK_EDGE", "confidence": 0.7},
    ]
    frag.operational_fingerprint = operational_fingerprint if operational_fingerprint is not None else {
        "change_proximity": {"nearest_change_hours": None},
        "vendor_upgrade": {"days_since_upgrade": None},
        "traffic_cycle": {"load_ratio_vs_baseline": 0.5},
        "concurrent_alarms": {"count_1h_window": 0},
    }
    frag.temporal_context = temporal_context or {
        "time_of_day_sin": 0.5,
        "time_of_day_cos": 0.5,
        "day_of_week_sin": 0.5,
        "day_of_week_cos": 0.5,
    }
    frag.event_timestamp = event_timestamp or datetime.now(timezone.utc)
    frag.created_at = created_at or datetime.now(timezone.utc)
    frag.base_relevance = base_relevance
    frag.current_decay_score = current_decay_score
    frag.near_miss_count = near_miss_count
    frag.updated_at = None
    frag.snapped_hypothesis_id = None
    return frag


def _build_engine(shadow_topo=None, event_bus=None):
    session_factory = MagicMock()
    shadow_topo = shadow_topo or AsyncMock()
    shadow_topo.topological_proximity = AsyncMock(return_value=0.5)
    event_bus = event_bus or AsyncMock()
    event_bus.publish = AsyncMock()
    return SnapEngine(
        session_factory=session_factory,
        shadow_topology=shadow_topo,
        event_bus=event_bus,
    )


# ---------------------------------------------------------------------------
# Test: Weight profiles from LLD §9
# ---------------------------------------------------------------------------

class TestWeightProfiles:
    """Verify WEIGHT_PROFILES match the LLD §9 specification."""

    def test_dark_edge_weights_sum_to_one(self):
        w = SnapEngine.WEIGHT_PROFILES["DARK_EDGE"]
        assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0

    def test_dark_node_weights_sum_to_one(self):
        w = SnapEngine.WEIGHT_PROFILES["DARK_NODE"]
        assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0

    def test_identity_mutation_weights_sum_to_one(self):
        w = SnapEngine.WEIGHT_PROFILES["IDENTITY_MUTATION"]
        assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0

    def test_phantom_ci_weights_sum_to_one(self):
        w = SnapEngine.WEIGHT_PROFILES["PHANTOM_CI"]
        assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0

    def test_dark_attribute_weights_sum_to_one(self):
        w = SnapEngine.WEIGHT_PROFILES["DARK_ATTRIBUTE"]
        assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0

    def test_dark_edge_entity_weight_is_025(self):
        """DARK_EDGE prioritises topology (0.35) but entity is 0.25."""
        assert SnapEngine.WEIGHT_PROFILES["DARK_EDGE"]["w_topo"] == 0.35
        assert SnapEngine.WEIGHT_PROFILES["DARK_EDGE"]["w_entity"] == 0.25

    def test_identity_mutation_entity_weight_is_045(self):
        """IDENTITY_MUTATION gives highest weight to entity overlap."""
        assert SnapEngine.WEIGHT_PROFILES["IDENTITY_MUTATION"]["w_entity"] == 0.45

    def test_all_profiles_present(self):
        expected = {"DARK_EDGE", "DARK_NODE", "IDENTITY_MUTATION", "PHANTOM_CI", "DARK_ATTRIBUTE"}
        assert set(SnapEngine.WEIGHT_PROFILES.keys()) == expected


# ---------------------------------------------------------------------------
# Test: Threshold constants from LLD §9
# ---------------------------------------------------------------------------

class TestThresholds:

    def test_snap_threshold(self):
        assert SnapEngine.SNAP_THRESHOLD == 0.75

    def test_near_miss_threshold(self):
        assert SnapEngine.NEAR_MISS_THRESHOLD == 0.55

    def test_affinity_threshold(self):
        assert SnapEngine.AFFINITY_THRESHOLD == 0.40

    def test_relevance_boost(self):
        assert SnapEngine.RELEVANCE_BOOST == 1.15


# ---------------------------------------------------------------------------
# Test: Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:

    def setup_method(self):
        self.engine = _build_engine()

    def test_identical_vectors_return_one(self):
        vec = [1.0, 0.0, 0.0]
        assert self.engine._cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert self.engine._cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_none_returns_zero(self):
        assert self.engine._cosine_similarity(None, [1.0]) == 0.0
        assert self.engine._cosine_similarity([1.0], None) == 0.0


# ---------------------------------------------------------------------------
# Test: Jaccard similarity
# ---------------------------------------------------------------------------

class TestJaccardSimilarity:

    def setup_method(self):
        self.engine = _build_engine()

    def test_identical_sets(self):
        assert self.engine._jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert self.engine._jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        # {a,b} ∩ {b,c} = {b}, union = {a,b,c}  → 1/3
        assert self.engine._jaccard_similarity({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_empty_sets(self):
        assert self.engine._jaccard_similarity(set(), set()) == 0.0


# ---------------------------------------------------------------------------
# Test: Temporal weight (LLD §9 formula)
# ---------------------------------------------------------------------------

class TestTemporalWeight:

    def setup_method(self):
        self.engine = _build_engine()

    def test_fresh_fragment_weight_near_one(self):
        now = datetime.now(timezone.utc)
        new = _mock_fragment(event_timestamp=now)
        stored = _mock_fragment(event_timestamp=now - timedelta(hours=1))
        w = self.engine._temporal_weight(new, stored)
        assert w > 0.8, f"Fresh fragment should have high temporal weight, got {w}"

    def test_old_fragment_weight_decays(self):
        now = datetime.now(timezone.utc)
        new = _mock_fragment(event_timestamp=now)
        stored = _mock_fragment(event_timestamp=now - timedelta(days=180))
        w = self.engine._temporal_weight(new, stored)
        assert w < 0.8, f"6-month-old fragment should have decayed weight, got {w}"

    def test_shared_change_proximity_boosts(self):
        now = datetime.now(timezone.utc)
        fp_near_change = {
            "change_proximity": {"nearest_change_hours": 12},
            "vendor_upgrade": {},
            "traffic_cycle": {"load_ratio_vs_baseline": 0.5},
            "concurrent_alarms": {"count_1h_window": 0},
        }
        new = _mock_fragment(event_timestamp=now, operational_fingerprint=fp_near_change)
        stored = _mock_fragment(
            event_timestamp=now - timedelta(hours=2),
            operational_fingerprint=fp_near_change,
        )
        w = self.engine._temporal_weight(new, stored)
        # With shared_change=1.0, bonus is (1 + 0.5*1.0) = 1.5×
        assert w > 1.0, "Shared change proximity should boost temporal weight above 1.0"

    def test_weight_is_clamped(self):
        """Temporal weight should be clamped to [0.01, 2.0]."""
        now = datetime.now(timezone.utc)
        new = _mock_fragment(event_timestamp=now)
        stored = _mock_fragment(event_timestamp=now)
        w = self.engine._temporal_weight(new, stored)
        assert 0.01 <= w <= 2.0


# ---------------------------------------------------------------------------
# Test: Entity identifier extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:

    def setup_method(self):
        self.engine = _build_engine()

    def test_extracts_from_list_of_dicts(self):
        frag = _mock_fragment(extracted_entities=[
            {"entity_identifier": "A"},
            {"entity_identifier": "B"},
        ])
        ids = self.engine._extract_entity_identifiers(frag)
        assert ids == ["A", "B"]

    def test_empty_entities(self):
        frag = _mock_fragment(extracted_entities=[])
        assert self.engine._extract_entity_identifiers(frag) == []

    def test_none_entities(self):
        frag = _mock_fragment(extracted_entities=None)
        frag.extracted_entities = None
        assert self.engine._extract_entity_identifiers(frag) == []


# ---------------------------------------------------------------------------
# Test: Failure mode extraction
# ---------------------------------------------------------------------------

class TestFailureModeExtraction:

    def setup_method(self):
        self.engine = _build_engine()

    def test_extracts_types(self):
        frag = _mock_fragment(failure_mode_tags=[
            {"divergence_type": "DARK_EDGE", "confidence": 0.7},
            {"divergence_type": "DARK_NODE", "confidence": 0.5},
        ])
        modes = self.engine._extract_failure_modes(frag)
        assert "DARK_EDGE" in modes
        assert "DARK_NODE" in modes


# ---------------------------------------------------------------------------
# Test: Compatible modes logic
# ---------------------------------------------------------------------------

class TestCompatibleModes:

    def setup_method(self):
        self.engine = _build_engine()

    def test_intersection_when_both_have_modes(self):
        new = _mock_fragment(failure_mode_tags=[
            {"divergence_type": "DARK_EDGE", "confidence": 0.7},
        ])
        stored = _mock_fragment(failure_mode_tags=[
            {"divergence_type": "DARK_EDGE", "confidence": 0.5},
            {"divergence_type": "DARK_NODE", "confidence": 0.3},
        ])
        modes = self.engine._compatible_modes(new, stored)
        assert "DARK_EDGE" in modes

    def test_all_profiles_when_no_tags(self):
        new = _mock_fragment(failure_mode_tags=[])
        stored = _mock_fragment(failure_mode_tags=[])
        modes = self.engine._compatible_modes(new, stored)
        assert set(modes) == set(SnapEngine.WEIGHT_PROFILES.keys())


# ---------------------------------------------------------------------------
# Test: Diurnal alignment
# ---------------------------------------------------------------------------

class TestDiurnalAlignment:

    def setup_method(self):
        self.engine = _build_engine()

    def test_same_time_gives_high_alignment(self):
        ctx = {
            "time_of_day_sin": 0.5,
            "time_of_day_cos": 0.866,
            "day_of_week_sin": 0.5,
            "day_of_week_cos": 0.866,
        }
        alignment = self.engine._diurnal_alignment(ctx, ctx)
        assert alignment > 0.9, "Same time context should give high diurnal alignment"

    def test_empty_contexts_return_moderate(self):
        alignment = self.engine._diurnal_alignment({}, {})
        # All zeros → dot=0, norms=1 → sim=0 → 0.5 + 0.5*(0+1)/2 = 0.75
        assert alignment == pytest.approx(0.75, abs=0.1)


# ---------------------------------------------------------------------------
# Test: Operational similarity
# ---------------------------------------------------------------------------

class TestOperationalSimilarity:

    def setup_method(self):
        self.engine = _build_engine()

    def test_identical_fingerprints(self):
        fp = {
            "change_proximity": {"nearest_change_hours": 12},
            "vendor_upgrade": {"days_since_upgrade": 5},
            "traffic_cycle": {"load_ratio_vs_baseline": 0.7},
            "concurrent_alarms": {"count_1h_window": 3},
        }
        sim = self.engine._operational_similarity(fp, fp)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_empty_fingerprints(self):
        sim = self.engine._operational_similarity({}, {})
        # Both have same defaults → should be 1.0
        assert sim == pytest.approx(1.0, abs=1e-6)
