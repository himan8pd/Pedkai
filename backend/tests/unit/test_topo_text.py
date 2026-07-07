"""Unit tests for RET-03: _build_topo_text must encode the neighbourhood.

Pure function tests, no DB. The method only reads its arguments (not `self`),
so we build the instance via ``__new__`` to avoid the ProvenanceLogger dependency.
"""

from dataclasses import dataclass
from typing import Optional

from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3


@dataclass
class _StubEntity:
    """Mimics ShadowEntityORM attribute access used by _build_topo_text."""

    id: str
    entity_identifier: str
    entity_domain: Optional[str] = None


@dataclass
class _StubRel:
    """Mimics ShadowRelationshipORM attribute access."""

    relationship_type: str
    from_entity_id: str = "a"
    to_entity_id: str = "b"


def _chain() -> EnrichmentChainV3:
    # Method under test does not touch instance state; skip __init__ deps.
    return EnrichmentChainV3.__new__(EnrichmentChainV3)


def _extracted():
    return [{"identifier": "eNB-100", "domain": "RAN"}]


def _base_text():
    return "Network topology context: eNB-100 (RAN)"


def _neighbourhood():
    ents = [
        _StubEntity(id="id-0", entity_identifier="eNB-100", entity_domain="RAN"),
        _StubEntity(id="id-1", entity_identifier="MME-1", entity_domain="CORE"),
        _StubEntity(id="id-2", entity_identifier="SGW-2", entity_domain="CORE"),
        _StubEntity(id="id-3", entity_identifier="PGW-3", entity_domain="CORE"),
    ]
    rels = [
        _StubRel(relationship_type="CONNECTS_TO"),
        _StubRel(relationship_type="CONNECTS_TO"),
        _StubRel(relationship_type="DEPENDS_ON"),
    ]
    return {
        "entities": ents,
        "relationships": rels,
        "depths": {0: ["id-0"], 1: ["id-1"], 2: ["id-2", "id-3"]},
        "total_entities": 4,
        "total_relationships": 3,
    }


def test_empty_dict_reproduces_current_output_exactly():
    chain = _chain()
    out = chain._build_topo_text(_extracted(), {})
    assert out == _base_text()


def test_none_neighbourhood_reproduces_current_output_exactly():
    chain = _chain()
    out = chain._build_topo_text(_extracted(), None)
    assert out == _base_text()


def test_empty_entities_and_relationships_reproduces_base():
    chain = _chain()
    nbr = {
        "entities": [],
        "relationships": [],
        "depths": {0: [], 1: [], 2: []},
        "total_entities": 0,
        "total_relationships": 0,
    }
    assert chain._build_topo_text(_extracted(), nbr) == _base_text()


def test_output_contains_depth1_identifiers_and_totals():
    chain = _chain()
    out = chain._build_topo_text(_extracted(), _neighbourhood())
    # Base extracted list preserved.
    assert out.startswith(_base_text())
    # Totals from neighbourhood.
    assert "Neighbourhood (4 entities, 3 links)" in out
    # depth-1 identifier resolved to "identifier (domain)".
    assert "depth-1: MME-1 (CORE)" in out
    # depth-2 identifiers resolved.
    assert "SGW-2 (CORE)" in out
    assert "PGW-3 (CORE)" in out


def test_output_contains_relationship_type_counts():
    chain = _chain()
    out = chain._build_topo_text(_extracted(), _neighbourhood())
    assert "Relationship types:" in out
    # CONNECTS_TO appears twice, DEPENDS_ON once.
    assert "CONNECTS_TO (2)" in out
    assert "DEPENDS_ON (1)" in out


def test_depth_labels_capped_at_15():
    chain = _chain()
    ents = [
        _StubEntity(id=f"id-{i}", entity_identifier=f"E{i}", entity_domain="RAN")
        for i in range(20)
    ]
    depth1_ids = [f"id-{i}" for i in range(20)]
    nbr = {
        "entities": ents,
        "relationships": [],
        "depths": {0: [], 1: depth1_ids, 2: []},
        "total_entities": 20,
        "total_relationships": 0,
    }
    out = chain._build_topo_text(_extracted(), nbr)
    # Only first 15 depth-1 labels present.
    assert "E14 (RAN)" in out
    assert "E15 (RAN)" not in out


def test_relationship_types_capped_at_8():
    chain = _chain()
    rels = [_StubRel(relationship_type=f"TYPE_{i}") for i in range(12)]
    nbr = {
        "entities": [_StubEntity(id="id-0", entity_identifier="X", entity_domain="RAN")],
        "relationships": rels,
        "depths": {0: [], 1: [], 2: []},
        "total_entities": 1,
        "total_relationships": 12,
    }
    out = chain._build_topo_text(_extracted(), nbr)
    # All 12 types have count 1; sorted by name, only first 8 kept.
    present = [f"TYPE_{i} (1)" for i in range(12) if f"TYPE_{i} (1)" in out]
    assert len(present) == 8


def test_string_keyed_depths_are_handled():
    chain = _chain()
    nbr = _neighbourhood()
    # Some callers/serialisers may key depths by strings.
    nbr["depths"] = {"0": ["id-0"], "1": ["id-1"], "2": ["id-2", "id-3"]}
    out = chain._build_topo_text(_extracted(), nbr)
    assert "depth-1: MME-1 (CORE)" in out


def test_never_exceeds_1500_chars():
    chain = _chain()
    ents = [
        _StubEntity(
            id=f"id-{i}",
            entity_identifier="X" * 200,
            entity_domain="LONGDOMAIN" * 20,
        )
        for i in range(30)
    ]
    nbr = {
        "entities": ents,
        "relationships": [
            _StubRel(relationship_type=f"REL_TYPE_LONG_{i}") for i in range(30)
        ],
        "depths": {
            0: [],
            1: [f"id-{i}" for i in range(15)],
            2: [f"id-{i}" for i in range(15, 30)],
        },
        "total_entities": 30,
        "total_relationships": 30,
    }
    out = chain._build_topo_text(_extracted(), nbr)
    assert len(out) <= 1500
