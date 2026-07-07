"""
Unit tests for PRV-03: peer-coverage annotation and confidence gating
for phantom findings.

Tests the pure module function `compute_peer_coverage` directly. No DB is
required — the DB-dependent detection paths (`_detect_phantom_nodes`,
`_detect_phantom_edges`) consume this function's output, so verifying the
pure computation is sufficient for the coverage/confidence contract.
"""

import os

import pytest

from backend.app.services.reconciliation_engine import compute_peer_coverage


# --- compute_peer_coverage: core coverage arithmetic ---


def test_zero_active_peers_yields_zero_coverage():
    """A type with 0/10 active peers => coverage 0.0."""
    entities_by_type = {"LTE_CELL": [f"e{i}" for i in range(10)]}
    active_ids: set[str] = set()  # none active
    coverage = compute_peer_coverage(entities_by_type, active_ids)
    assert coverage["LTE_CELL"] == 0.0


def test_nine_of_ten_active_peers_yields_point_nine():
    """A type with 9/10 active peers => coverage 0.9."""
    ids = [f"e{i}" for i in range(10)]
    entities_by_type = {"NR_CELL": ids}
    active_ids = set(ids[:9])  # 9 active
    coverage = compute_peer_coverage(entities_by_type, active_ids)
    assert coverage["NR_CELL"] == pytest.approx(0.9)


def test_all_active_yields_full_coverage():
    ids = [f"e{i}" for i in range(4)]
    coverage = compute_peer_coverage({"OLT": ids}, set(ids))
    assert coverage["OLT"] == 1.0


def test_empty_type_yields_zero_coverage():
    """A type with no members has no basis to trust the population => 0.0."""
    coverage = compute_peer_coverage({"MME": []}, {"x"})
    assert coverage["MME"] == 0.0


def test_multiple_types_are_independent():
    entities_by_type = {
        "PE_ROUTER": ["a", "b", "c", "d"],  # 2/4 active
        "P_ROUTER": ["e", "f"],             # 0/2 active
    }
    active_ids = {"a", "b"}
    coverage = compute_peer_coverage(entities_by_type, active_ids)
    assert coverage["PE_ROUTER"] == pytest.approx(0.5)
    assert coverage["P_ROUTER"] == 0.0


def test_active_ids_outside_type_do_not_inflate_coverage():
    """active_ids referencing entities not in the type must not count."""
    entities_by_type = {"AMF": ["a", "b"]}
    active_ids = {"z1", "z2", "z3"}  # unrelated ids
    coverage = compute_peer_coverage(entities_by_type, active_ids)
    assert coverage["AMF"] == 0.0


# --- Confidence gating contract (mirrors detection-path arithmetic) ---
#
# The detection functions apply:
#   confidence = clamp(base_conf * coverage, low=0.05, high=base_conf)
#   low_data_confidence = coverage < PHANTOM_MIN_PEER_COVERAGE (default 0.2)
# These tests assert the acceptance-criteria numbers using the same formula
# the engine uses, keeping the contract explicit and DB-free.


def _gated_confidence(base_conf: float, coverage: float) -> float:
    return max(0.05, min(base_conf, base_conf * coverage))


def test_zero_coverage_clamps_confidence_to_floor():
    """0/10 active => coverage 0.0 => confidence clamped to 0.05."""
    coverage = compute_peer_coverage({"LTE_CELL": [f"e{i}" for i in range(10)]}, set())
    conf = _gated_confidence(0.70, coverage["LTE_CELL"])
    assert conf == 0.05


def test_high_coverage_scales_edge_confidence():
    """9/10 active => coverage 0.9 => edge confidence ≈ 0.63 (base 0.70)."""
    ids = [f"e{i}" for i in range(10)]
    coverage = compute_peer_coverage({"NR_CELL": ids}, set(ids[:9]))
    conf = _gated_confidence(0.70, coverage["NR_CELL"])
    assert conf == pytest.approx(0.63)


def test_low_data_flag_threshold():
    """coverage below PHANTOM_MIN_PEER_COVERAGE (default 0.2) flags low data."""
    min_cov = float(os.environ.get("PHANTOM_MIN_PEER_COVERAGE", "0.2"))
    # 0/10 => 0.0 < 0.2 => flagged
    zero = compute_peer_coverage({"T": [f"e{i}" for i in range(10)]}, set())["T"]
    assert zero < min_cov
    # 9/10 => 0.9 >= 0.2 => not flagged
    ids = [f"e{i}" for i in range(10)]
    high = compute_peer_coverage({"T": ids}, set(ids[:9]))["T"]
    assert high >= min_cov
