from math import prod

from .base import EvidenceFusionMethodology, EvidenceProfile


class NoisyORFusion(EvidenceFusionMethodology):
    """Noisy-OR gate evidence fusion.

    Combines independent evidence probabilities using the Noisy-OR formula:
        P(H) = 1 - product(1 - p_i for each evidence probability p_i)

    Appropriate when evidence sources are conditionally independent and
    telemetry is rich enough to estimate per-source inhibition probabilities.
    """

    def combine(self, evidence_probabilities: list[float]) -> float:
        """Combine independent evidence probabilities via Noisy-OR.

        Args:
            evidence_probabilities: List of probabilities in [0, 1], one per
                independent evidence source.

        Returns:
            Fused hypothesis confidence in [0, 1].
        """
        if not evidence_probabilities:
            return 0.0
        return 1.0 - prod(1.0 - p for p in evidence_probabilities)

    def name(self) -> str:
        return "noisy_or"

    def is_appropriate_for(self, evidence_profile: EvidenceProfile) -> bool:
        """Noisy-OR is appropriate when telemetry is rich OR evidence is not sparse."""
        return evidence_profile.has_rich_telemetry or not evidence_profile.is_sparse
