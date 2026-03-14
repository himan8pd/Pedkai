"""Unit tests for DempsterShaferFusion (TASK-105)."""

import pytest

from backend.app.services.fusion.base import EvidenceProfile
from backend.app.services.fusion.dempster_shafer import DempsterShaferFusion
from backend.app.services.fusion.factory import FusionMethodologyFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(
    source_count: int = 1,
    is_sparse: bool = False,
    has_qualitative_assessments: bool = False,
    has_rich_telemetry: bool = False,
) -> EvidenceProfile:
    return EvidenceProfile(
        source_count=source_count,
        is_sparse=is_sparse,
        has_qualitative_assessments=has_qualitative_assessments,
        has_rich_telemetry=has_rich_telemetry,
    )


# ---------------------------------------------------------------------------
# DempsterShaferFusion unit tests
# ---------------------------------------------------------------------------

class TestDempsterShaferFusion:

    # Test 1 — identity
    def test_name_returns_dempster_shafer(self):
        assert DempsterShaferFusion().name() == "dempster_shafer"

    # Test 2 — single evidence passthrough
    def test_single_evidence_passthrough(self):
        """A single probability should pass through unchanged."""
        result = DempsterShaferFusion().combine([0.8])
        assert result == pytest.approx(0.8)

    # Test 3 — high-agreement amplification
    def test_two_high_agreement_sources_amplify(self):
        """Two strongly agreeing sources should produce a combined belief
        greater than the maximum individual belief (amplification property)."""
        probs = [0.9, 0.85]
        result = DempsterShaferFusion().combine(probs)
        assert result > max(probs), (
            f"Expected amplification above {max(probs):.4f}, got {result:.4f}"
        )

    # Test 4 — high conflict graceful degradation
    def test_high_conflict_returns_average(self):
        """Sources [0.95, 0.05] produce high conflict (K ~ 0.362, above the
        threshold of 0.35); the result should fall back to the arithmetic mean
        (0.5) rather than raising or producing an extreme result."""
        probs = [0.95, 0.05]
        result = DempsterShaferFusion().combine(probs)
        expected_avg = sum(probs) / len(probs)
        assert result == pytest.approx(expected_avg, abs=1e-9), (
            f"High-conflict fallback expected exactly {expected_avg:.3f}, got {result:.4f}"
        )

    # Test 5 — empty list
    def test_empty_evidence_returns_zero(self):
        assert DempsterShaferFusion().combine([]) == 0.0

    # Test 6 — is_appropriate_for with qualitative assessments
    def test_appropriate_for_qualitative_assessments(self):
        profile = _make_profile(source_count=1, has_qualitative_assessments=True)
        assert DempsterShaferFusion().is_appropriate_for(profile) is True

    # Test 7 — is_appropriate_for fails for sparse, single, no qualitative
    def test_not_appropriate_for_single_source_no_qualitative(self):
        profile = _make_profile(
            source_count=1,
            is_sparse=True,
            has_qualitative_assessments=False,
        )
        assert DempsterShaferFusion().is_appropriate_for(profile) is False

    # Test 8 — factory registration
    def test_factory_create_returns_dempster_shafer_instance(self):
        instance = FusionMethodologyFactory.create("dempster_shafer")
        assert isinstance(instance, DempsterShaferFusion)

    # Additional edge-case tests
    def test_is_appropriate_for_multiple_sources(self):
        """source_count >= 2 is sufficient even without qualitative assessments."""
        profile = _make_profile(source_count=2, has_qualitative_assessments=False)
        assert DempsterShaferFusion().is_appropriate_for(profile) is True

    def test_three_agreeing_sources_strong_belief(self):
        """Three moderately confident sources should produce a high combined belief."""
        result = DempsterShaferFusion().combine([0.7, 0.75, 0.72])
        assert result > 0.9, (
            f"Three agreeing sources at ~0.72 should exceed 0.9, got {result:.4f}"
        )

    def test_combine_probabilities_bounded(self):
        """Combined belief must remain in [0, 1]."""
        for probs in ([0.5, 0.5], [0.99, 0.99], [0.1, 0.9], [0.3, 0.4, 0.5]):
            result = DempsterShaferFusion().combine(probs)
            assert 0.0 <= result <= 1.0, (
                f"Result {result} out of bounds for probs={probs}"
            )

    def test_single_zero_probability(self):
        """Zero anomaly evidence → zero combined belief."""
        assert DempsterShaferFusion().combine([0.0]) == pytest.approx(0.0)

    def test_single_unit_probability(self):
        """Certain anomaly evidence → combined belief of 1.0."""
        assert DempsterShaferFusion().combine([1.0]) == pytest.approx(1.0)
