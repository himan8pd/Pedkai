"""Unit tests for _compute_dedup_key content-based fallback (BLK-03).

When source_ref is absent, the dedup key must be derived from raw_content so
ref-less sources cannot create unlimited duplicate fragments. Existing
source_ref behaviour must remain unchanged.
"""
from datetime import datetime, timezone

from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
from backend.app.services.abeyance.events import ProvenanceLogger


def _chain() -> EnrichmentChainV3:
    return EnrichmentChainV3(provenance=ProvenanceLogger())


TS = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)


def test_no_source_ref_same_content_same_key():
    chain = _chain()
    k1 = chain._compute_dedup_key("t1", "ALARM", None, TS, raw_content="disk failure on node-7")
    k2 = chain._compute_dedup_key("t1", "ALARM", None, TS, raw_content="disk failure on node-7")
    assert k1 is not None
    assert k1 == k2


def test_no_source_ref_different_content_different_key():
    chain = _chain()
    k1 = chain._compute_dedup_key("t1", "ALARM", None, TS, raw_content="disk failure on node-7")
    k2 = chain._compute_dedup_key("t1", "ALARM", None, TS, raw_content="link down on node-3")
    assert k1 is not None
    assert k2 is not None
    assert k1 != k2


def test_no_source_ref_empty_content_still_non_none():
    chain = _chain()
    k = chain._compute_dedup_key("t1", "ALARM", None, TS)
    assert k is not None
    assert len(k) == 64


def test_source_ref_behaviour_unchanged():
    chain = _chain()
    key = chain._compute_dedup_key("t1", "ALARM", "REF-1", TS)
    # Same expression as before the change: sha256 of tenant:type:ref:iso.
    import hashlib
    expected = hashlib.sha256(
        f"t1:ALARM:REF-1:{TS.isoformat()}".encode()
    ).hexdigest()[:64]
    assert key == expected
    # raw_content must not affect the source_ref branch.
    key_with_content = chain._compute_dedup_key(
        "t1", "ALARM", "REF-1", TS, raw_content="anything at all"
    )
    assert key_with_content == expected
