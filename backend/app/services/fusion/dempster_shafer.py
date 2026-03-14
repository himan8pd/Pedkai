"""Dempster-Shafer evidence fusion methodology.

Implements Dempster's combination rule over a binary frame of discernment:
    Theta = {anomaly, no_anomaly, uncertainty}

Each raw probability p is interpreted as the Basic Probability Assignment (BPA)
for the focal element "anomaly". The complementary mass (1 - p) is split as:
    - 0.4 * (1 - p) → no_anomaly
    - 0.6 * (1 - p) → uncertainty

This asymmetric split makes DS suitable for uncertain monitoring environments
where silence is more often uncertainty than confirmed absence.  Because
"uncertainty" is treated as the full frame Theta (open-world assignment), it
never contributes to the conflict K.  With 60 % of the complement going to
uncertainty, the theoretical maximum K for two sources is ~0.40.

Conflict handling: when K >= _HIGH_CONFLICT_THRESHOLD (calibrated relative to
the maximum achievable K for this BPA model), graceful degradation returns the
arithmetic mean of input probabilities instead of an ill-conditioned result.
A threshold of 0.35 catches genuine diametrically-opposed evidence pairs
(e.g. [0.95, 0.05]) while well-below the agreement region (K <= 0.10).
"""

from .base import EvidenceFusionMethodology, EvidenceProfile

# Fraction of the complementary mass (1-p) assigned to no_anomaly
_NO_ANOMALY_FRACTION = 0.4
# Fraction of the complementary mass (1-p) assigned to uncertainty
_UNCERTAINTY_FRACTION = 0.6

# Conflict threshold above which we fall back to arithmetic mean.
# With the BPA split above, max theoretical K ≈ 0.40; 0.35 reliably separates
# conflicting pairs (e.g. [0.95, 0.05] → K ≈ 0.362) from agreement cases.
_HIGH_CONFLICT_THRESHOLD = 0.35


def _bpa_from_probability(p: float) -> dict[str, float]:
    """Convert a raw anomaly probability into a three-element BPA.

    Args:
        p: Probability in [0, 1] representing belief that anomaly is present.

    Returns:
        Dict with keys "anomaly", "no_anomaly", "uncertainty" that sum to 1.0.
    """
    complement = 1.0 - p
    return {
        "anomaly": p,
        "no_anomaly": _NO_ANOMALY_FRACTION * complement,
        "uncertainty": _UNCERTAINTY_FRACTION * complement,
    }


def _combine_two(
    m1: dict[str, float], m2: dict[str, float]
) -> dict[str, float]:
    """Apply Dempster's combination rule to two mass assignments.

    Formula:
        m12(A) = (1 / (1 - K)) * sum_{B ∩ C = A} m1(B) * m2(C)

    where K = sum_{B ∩ C = ∅} m1(B) * m2(C) is the conflict mass.

    When K >= _HIGH_CONFLICT_THRESHOLD the caller should detect this and
    invoke fallback; this function still returns the raw (not normalised)
    combined masses so the caller can inspect K.

    Returns:
        Tuple of (combined_masses_dict, K).  The masses are NOT normalised
        yet (caller divides by 1-K after checking for high conflict).
    """
    hypotheses = ("anomaly", "no_anomaly", "uncertainty")

    # Compute pairwise intersection products.
    # "uncertainty" acts as an open world / vacuous assignment — it does not
    # intersect to empty with anything (it represents Theta itself).
    combined: dict[str, float] = {h: 0.0 for h in hypotheses}
    conflict = 0.0

    for focal1, mass1 in m1.items():
        for focal2, mass2 in m2.items():
            product = mass1 * mass2
            if focal1 == focal2:
                # Identical singletons — intersection is themselves.
                combined[focal1] += product
            elif focal1 == "uncertainty":
                # uncertainty ∩ X = X
                combined[focal2] += product
            elif focal2 == "uncertainty":
                # X ∩ uncertainty = X
                combined[focal1] += product
            else:
                # Two distinct singletons — empty intersection → conflict
                conflict += product

    return combined, conflict


class DempsterShaferFusion(EvidenceFusionMethodology):
    """Evidence fusion using Dempster's combination rule.

    Appropriate for environments where qualitative assessments (e.g. expert
    reports, rule-based flags) are present, or when at least two independent
    evidence sources are available to benefit from the amplification property.
    """

    def combine(self, evidence_probabilities: list[float]) -> float:
        """Fuse evidence probabilities using Dempster's rule.

        Each probability is converted to a BPA and then combined pairwise.
        Returns the final combined mass assigned to the "anomaly" hypothesis.

        Args:
            evidence_probabilities: List of anomaly probabilities in [0, 1].

        Returns:
            Fused belief in [0, 1] for the anomaly hypothesis.
        """
        if not evidence_probabilities:
            return 0.0

        if len(evidence_probabilities) == 1:
            return evidence_probabilities[0]

        # Convert all probabilities to BPAs
        bpas = [_bpa_from_probability(p) for p in evidence_probabilities]

        # Accumulate by combining pairwise left-to-right
        accumulated = bpas[0]
        total_conflict = 0.0

        for bpa in bpas[1:]:
            raw_combined, conflict = _combine_two(accumulated, bpa)
            total_conflict = conflict  # last pairwise conflict (used for detection)

            if conflict >= _HIGH_CONFLICT_THRESHOLD:
                # High conflict: graceful degradation — return arithmetic mean
                return sum(evidence_probabilities) / len(evidence_probabilities)

            normaliser = 1.0 - conflict
            accumulated = {h: v / normaliser for h, v in raw_combined.items()}

        return accumulated["anomaly"]

    def name(self) -> str:
        return "dempster_shafer"

    def is_appropriate_for(self, evidence_profile: EvidenceProfile) -> bool:
        """DS is appropriate when qualitative assessments are present OR there
        are at least two evidence sources (so combination amplification applies).

        Args:
            evidence_profile: Descriptor of the current evidence context.

        Returns:
            True when DS is a suitable fusion choice.
        """
        return (
            evidence_profile.has_qualitative_assessments
            or evidence_profile.source_count >= 2
        )
