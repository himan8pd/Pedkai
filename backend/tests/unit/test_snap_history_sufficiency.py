"""Unit tests for _classify_sufficiency (PRV-01).

Verifies dimension-mask normalisation and evidence-sufficiency thresholds for
the snap-history provenance exposure. entity_overlap always counts as active.
"""

from backend.app.api.abeyance import _classify_sufficiency


def test_none_input_is_minimal():
    # Only entity_overlap counts -> 1 dimension -> minimal.
    assert _classify_sufficiency(None) == "minimal"


def test_empty_dict_is_minimal():
    assert _classify_sufficiency({}) == "minimal"


def test_full_threshold_long_keys():
    # 3 explicit True + entity_overlap = 4 dimensions -> full.
    masks = {"semantic": True, "topological": True, "temporal": True}
    assert _classify_sufficiency(masks) == "full"


def test_partial_lower_bound():
    # 1 explicit True + entity_overlap = 2 dimensions -> partial.
    assert _classify_sufficiency({"semantic": True}) == "partial"


def test_partial_upper_bound():
    # 2 explicit True + entity_overlap = 3 dimensions -> partial.
    assert _classify_sufficiency({"semantic": True, "operational": True}) == "partial"


def test_full_all_dimensions():
    masks = {
        "semantic": True,
        "topological": True,
        "temporal": True,
        "operational": True,
    }
    assert _classify_sufficiency(masks) == "full"


def test_false_values_not_counted():
    # All False explicit dims -> only entity_overlap -> minimal.
    masks = {"semantic": False, "topological": False, "temporal": False}
    assert _classify_sufficiency(masks) == "minimal"


def test_short_and_long_keys_classify_identically():
    long_key = {"semantic": True, "topological": True, "temporal": True}
    short_key = {"sem": True, "topo": True, "temp": True}
    assert _classify_sufficiency(long_key) == _classify_sufficiency(short_key) == "full"


def test_short_key_partial_equivalence():
    long_key = {"operational": True}
    short_key = {"oper": True}
    assert _classify_sufficiency(long_key) == _classify_sufficiency(short_key) == "partial"


def test_mixed_short_and_long_keys():
    # sem (short) + operational (long) + entity_overlap = 3 -> partial.
    masks = {"sem": True, "operational": True}
    assert _classify_sufficiency(masks) == "partial"


def test_explicit_entity_overlap_not_double_counted():
    # entity_overlap passed explicitly should not add a duplicate dimension.
    masks = {"entity_overlap": True, "semantic": True}
    assert _classify_sufficiency(masks) == "partial"
