"""Unit tests for FusionMethodologyFactory and NoisyORFusion (TASK-104)."""

import pytest

from backend.app.services.fusion.base import EvidenceProfile, EvidenceFusionMethodology
from backend.app.services.fusion.noisy_or import NoisyORFusion
from backend.app.services.fusion.factory import FusionMethodologyFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rich_profile() -> EvidenceProfile:
    return EvidenceProfile(
        source_count=3,
        is_sparse=False,
        has_qualitative_assessments=False,
        has_rich_telemetry=True,
    )


def _sparse_profile() -> EvidenceProfile:
    return EvidenceProfile(
        source_count=1,
        is_sparse=True,
        has_qualitative_assessments=True,
        has_rich_telemetry=False,
    )


# ---------------------------------------------------------------------------
# NoisyORFusion unit tests
# ---------------------------------------------------------------------------

class TestNoisyORFusion:
    def test_name(self):
        assert NoisyORFusion().name() == "noisy_or"

    def test_combine_standard_case(self):
        """1 - (0.3 * 0.2 * 0.4) = 1 - 0.024 = 0.976"""
        result = NoisyORFusion().combine([0.7, 0.8, 0.6])
        assert abs(result - 0.976) < 0.001

    def test_combine_single_evidence(self):
        """Single probability passes through unchanged."""
        assert NoisyORFusion().combine([0.5]) == pytest.approx(0.5)

    def test_combine_empty_evidence(self):
        """No evidence → zero belief."""
        assert NoisyORFusion().combine([]) == 0.0

    def test_combine_certain_evidence(self):
        """Any certainty (p=1.0) → combined certainty."""
        assert NoisyORFusion().combine([0.5, 1.0, 0.3]) == pytest.approx(1.0)

    def test_combine_zero_evidence(self):
        """All zeros → zero combined."""
        assert NoisyORFusion().combine([0.0, 0.0]) == pytest.approx(0.0)

    def test_is_appropriate_for_rich_telemetry(self):
        assert NoisyORFusion().is_appropriate_for(_rich_profile()) is True

    def test_is_appropriate_for_non_sparse(self):
        profile = EvidenceProfile(
            source_count=2,
            is_sparse=False,
            has_qualitative_assessments=False,
            has_rich_telemetry=False,
        )
        assert NoisyORFusion().is_appropriate_for(profile) is True

    def test_not_appropriate_for_sparse_no_rich_telemetry(self):
        assert NoisyORFusion().is_appropriate_for(_sparse_profile()) is False


# ---------------------------------------------------------------------------
# FusionMethodologyFactory tests
# ---------------------------------------------------------------------------

class TestFusionMethodologyFactory:
    def test_create_returns_noisy_or(self):
        instance = FusionMethodologyFactory.create("noisy_or")
        assert isinstance(instance, NoisyORFusion)

    def test_create_unknown_name_raises_key_error(self):
        with pytest.raises(KeyError, match="unknown_method"):
            FusionMethodologyFactory.create("unknown_method")

    def test_select_for_profile_rich_telemetry_returns_noisy_or(self):
        instance = FusionMethodologyFactory.select_for_profile(_rich_profile())
        assert isinstance(instance, NoisyORFusion)

    def test_select_for_profile_no_appropriate_methodology_raises_runtime_error(self):
        """Verify RuntimeError when no methodology suits the profile.

        We use a temporary isolated factory subclass to avoid polluting the
        global registry with stubs from other tests.
        """

        class _IsolatedFactory(FusionMethodologyFactory):
            _registry = {}

        class _NeverAppropriate(EvidenceFusionMethodology):
            def combine(self, evidence_probabilities):
                return 0.0

            def name(self):
                return "never"

            def is_appropriate_for(self, profile):
                return False

        _IsolatedFactory.register("never", _NeverAppropriate)

        with pytest.raises(RuntimeError, match="No registered fusion methodology"):
            _IsolatedFactory.select_for_profile(_sparse_profile())

    def test_register_custom_class_and_create(self):
        """Registering a custom methodology makes it available via create()."""

        class _DummyFusion(EvidenceFusionMethodology):
            def combine(self, evidence_probabilities):
                return sum(evidence_probabilities) / max(len(evidence_probabilities), 1)

            def name(self):
                return "mean_fusion"

            def is_appropriate_for(self, profile):
                return profile.has_qualitative_assessments

        FusionMethodologyFactory.register("mean_fusion", _DummyFusion)

        instance = FusionMethodologyFactory.create("mean_fusion")
        assert isinstance(instance, _DummyFusion)
        assert instance.combine([0.4, 0.6]) == pytest.approx(0.5)

        # Clean up so other tests are not affected
        del FusionMethodologyFactory._registry["mean_fusion"]

    def test_select_for_profile_uses_custom_class(self):
        """select_for_profile returns a custom class when it's appropriate."""

        class _QualFusion(EvidenceFusionMethodology):
            def combine(self, evidence_probabilities):
                return max(evidence_probabilities, default=0.0)

            def name(self):
                return "qual_fusion"

            def is_appropriate_for(self, profile):
                return profile.has_qualitative_assessments and profile.is_sparse

        FusionMethodologyFactory.register("qual_fusion", _QualFusion)

        instance = FusionMethodologyFactory.select_for_profile(_sparse_profile())
        assert isinstance(instance, _QualFusion)

        # Clean up
        del FusionMethodologyFactory._registry["qual_fusion"]
