"""Tests for EnrichmentChain — the 4-step evidence enrichment pipeline.

Tests entity resolution from alarm/text, topology expansion call,
fingerprint construction, failure mode classification per type,
temporal context sinusoidal encoding, and enriched embedding dimensionality.

Uses mocked services — no live database required.

LLD ref: §6 (The Enrichment Chain), §7 (Temporal-Semantic Embedding)
"""

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.app.schemas.abeyance import (
    FailureModeTag,
    OperationalFingerprint,
    RawEvidence,
    SourceType,
    TemporalContext,
)
from backend.app.services.abeyance.enrichment_chain import EnrichmentChain, _time_bucket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_shadow_topology():
    topo = AsyncMock()
    topo.get_neighbourhood = AsyncMock(return_value=MagicMock(
        entities=[],
        relationships=[],
    ))
    return topo


def _mock_embedding_service():
    svc = AsyncMock()
    svc.generate_embedding = AsyncMock(return_value=[0.1] * 3072)
    return svc


def _build_chain(embedding_svc=None, shadow_topo=None, llm_svc=None):
    return EnrichmentChain(
        embedding_service=embedding_svc or _mock_embedding_service(),
        shadow_topology=shadow_topo or _mock_shadow_topology(),
        llm_service=llm_svc,
    )


# ---------------------------------------------------------------------------
# Test: Enriched embedding dimensions (LLD §6 Step 4)
# ---------------------------------------------------------------------------

class TestEnrichedEmbeddingDimensions:

    def test_semantic_dim(self):
        assert EnrichmentChain.SEMANTIC_DIM == 512

    def test_topological_dim(self):
        assert EnrichmentChain.TOPOLOGICAL_DIM == 384

    def test_temporal_dim(self):
        assert EnrichmentChain.TEMPORAL_DIM == 256

    def test_operational_dim(self):
        assert EnrichmentChain.OPERATIONAL_DIM == 384

    def test_total_enriched_dim(self):
        """Enriched embedding is 512+384+256+384 = 1536 dimensions."""
        total = (
            EnrichmentChain.SEMANTIC_DIM
            + EnrichmentChain.TOPOLOGICAL_DIM
            + EnrichmentChain.TEMPORAL_DIM
            + EnrichmentChain.OPERATIONAL_DIM
        )
        assert total == 1536
        assert EnrichmentChain.ENRICHED_DIM == 1536


# ---------------------------------------------------------------------------
# Test: Regex entity extraction
# ---------------------------------------------------------------------------

class TestRegexEntityExtraction:

    def setup_method(self):
        self.chain = _build_chain()

    def test_extracts_cell_ids(self):
        content = "Cell LTE-8842-A showing degraded throughput"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert "LTE-8842-A" in ids

    def test_extracts_site_ids(self):
        content = "Investigating SITE-NW-1847 for outage"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert "SITE-NW-1847" in ids

    def test_extracts_ip_addresses(self):
        content = "Traffic on 192.168.1.100 dropped"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert "192.168.1.100" in ids

    def test_extracts_enodeb(self):
        content = "eNodeB ENB-12345 alarm raised"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert any("ENB" in i for i in ids)

    def test_extracts_vlan(self):
        content = "VLAN100 experiencing congestion"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert any("VLAN" in i for i in ids)

    def test_deduplicates(self):
        content = "LTE-001-A and LTE-001-A repeated"
        entities = self.chain._regex_extract_entities(content)
        ids = [e["entity_identifier"] for e in entities]
        assert ids.count("LTE-001-A") == 1

    def test_no_entities_in_plain_text(self):
        content = "The weather is nice today"
        entities = self.chain._regex_extract_entities(content)
        assert len(entities) == 0


# ---------------------------------------------------------------------------
# Test: Failure mode classification (LLD §6 Step 3)
# ---------------------------------------------------------------------------

class TestFailureModeClassification:

    def setup_method(self):
        self.chain = _build_chain()
        self.default_fp = OperationalFingerprint(
            change_proximity={"nearest_change_hours": None},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={"count_1h_window": 0},
            open_incidents=[],
        )

    def test_dark_edge_cross_domain(self):
        """Cross-domain entity references → DARK_EDGE."""
        entity_refs = [
            {"entity_identifier": "ENT-1", "entity_domain": "RAN"},
            {"entity_identifier": "ENT-2", "entity_domain": "TRANSPORT"},
        ]
        tags = self.chain._classify_failure_modes(entity_refs, [], self.default_fp, "cross domain issue")
        types = [t.divergence_type for t in tags]
        assert "DARK_EDGE" in types

    def test_dark_node_unknown_entity(self):
        """Content mentioning 'unknown' entity → DARK_NODE."""
        entity_refs = [{"entity_identifier": "ENT-1", "entity_domain": "RAN"}]
        tags = self.chain._classify_failure_modes(
            entity_refs, [], self.default_fp,
            "Entity not found in CMDB, unknown device detected"
        )
        types = [t.divergence_type for t in tags]
        assert "DARK_NODE" in types

    def test_phantom_node(self):
        """Content mentioning 'zero user' or 'inactive' → PHANTOM_NODE."""
        entity_refs = [{"entity_identifier": "ENT-1", "entity_domain": "RAN"}]
        tags = self.chain._classify_failure_modes(
            entity_refs, [], self.default_fp,
            "Cell shows zero user connections, inactive since Tuesday"
        )
        types = [t.divergence_type for t in tags]
        assert "PHANTOM_NODE" in types

    def test_identity_mutation(self):
        """Content mentioning 'serial mismatch' → IDENTITY_MUTATION."""
        entity_refs = [{"entity_identifier": "ENT-1", "entity_domain": "RAN"}]
        tags = self.chain._classify_failure_modes(
            entity_refs, [], self.default_fp,
            "Serial mismatch detected on the replaced hardware"
        )
        types = [t.divergence_type for t in tags]
        assert "IDENTITY_MUTATION" in types

    def test_dark_attribute_post_change(self):
        """Near change window + parameter keyword → DARK_ATTRIBUTE."""
        fp = OperationalFingerprint(
            change_proximity={"nearest_change_hours": 12},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={"count_1h_window": 0},
            open_incidents=[],
        )
        entity_refs = [{"entity_identifier": "ENT-1", "entity_domain": "RAN"}]
        tags = self.chain._classify_failure_modes(
            entity_refs, [], fp,
            "Parameter drift detected after recent config change"
        )
        types = [t.divergence_type for t in tags]
        assert "DARK_ATTRIBUTE" in types

    def test_default_tag_when_no_specific_mode(self):
        """No specific keywords → default DARK_EDGE with low confidence."""
        entity_refs = [{"entity_identifier": "ENT-1", "entity_domain": "RAN"}]
        tags = self.chain._classify_failure_modes(
            entity_refs, [], self.default_fp,
            "Normal alarm cleared"
        )
        assert len(tags) >= 1
        assert tags[0].divergence_type == "DARK_EDGE"
        assert tags[0].confidence < 0.5  # Low confidence default


# ---------------------------------------------------------------------------
# Test: Temporal context (LLD §7)
# ---------------------------------------------------------------------------

class TestTemporalContext:

    def setup_method(self):
        self.chain = _build_chain()

    def test_sinusoidal_time_of_day(self):
        """Time-of-day encoding uses sin/cos with 24-hour period."""
        fp = OperationalFingerprint(
            change_proximity={"nearest_change_hours": None},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={},
            open_incidents=[],
        )
        # Noon UTC (hour=12)
        noon = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        ctx = self.chain._build_temporal_context(noon, fp)

        expected_sin = math.sin(2 * math.pi * 12 / 24)  # sin(π) ≈ 0
        expected_cos = math.cos(2 * math.pi * 12 / 24)  # cos(π) = -1
        assert ctx.time_of_day_sin == pytest.approx(expected_sin, abs=1e-6)
        assert ctx.time_of_day_cos == pytest.approx(expected_cos, abs=1e-6)

    def test_sinusoidal_day_of_week(self):
        """Day-of-week encoding uses sin/cos with 7-day period."""
        fp = OperationalFingerprint(
            change_proximity={"nearest_change_hours": None},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={},
            open_incidents=[],
        )
        # Sunday (weekday() = 6)
        sunday = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        ctx = self.chain._build_temporal_context(sunday, fp)

        dow = sunday.weekday()
        expected_sin = math.sin(2 * math.pi * dow / 7)
        expected_cos = math.cos(2 * math.pi * dow / 7)
        assert ctx.day_of_week_sin == pytest.approx(expected_sin, abs=1e-6)
        assert ctx.day_of_week_cos == pytest.approx(expected_cos, abs=1e-6)


# ---------------------------------------------------------------------------
# Test: Enriched embedding construction
# ---------------------------------------------------------------------------

class TestEnrichedEmbedding:

    def setup_method(self):
        self.chain = _build_chain()

    def test_enriched_embedding_is_1536_dim(self):
        """Constructed enriched embedding should be exactly 1536 dimensions."""
        ctx = TemporalContext(
            norm_timestamp=0.5,
            time_of_day_sin=0.5,
            time_of_day_cos=0.5,
            day_of_week_sin=0.5,
            day_of_week_cos=0.5,
            change_proximity=0.0,
            vendor_upgrade_recency=0.0,
            traffic_load_ratio=0.5,
            seasonal_sin=0.0,
            seasonal_cos=1.0,
        )
        fp = OperationalFingerprint(
            change_proximity={"nearest_change_hours": None},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={},
            open_incidents=[],
        )
        embedding = self.chain._construct_enriched_embedding(
            raw_embedding=[0.1] * 768,
            entity_refs=[{"entity_identifier": "A", "entity_domain": "RAN"}],
            neighbourhood={},
            temporal_ctx=ctx,
            fingerprint=fp,
            failure_tags=[FailureModeTag(
                divergence_type="DARK_EDGE",
                confidence=0.5,
                rationale="test",
            )],
        )
        assert len(embedding) == 1536

    def test_enriched_embedding_is_normalised(self):
        """Enriched embedding should be L2-normalised."""
        ctx = TemporalContext(
            norm_timestamp=0.5,
            time_of_day_sin=0.5,
            time_of_day_cos=0.5,
            day_of_week_sin=0.5,
            day_of_week_cos=0.5,
        )
        fp = OperationalFingerprint(
            change_proximity={},
            vendor_upgrade={},
            traffic_cycle={"load_ratio_vs_baseline": 0.5},
            concurrent_alarms={},
            open_incidents=[],
        )
        embedding = self.chain._construct_enriched_embedding(
            raw_embedding=[0.1] * 768,
            entity_refs=[],
            neighbourhood={},
            temporal_ctx=ctx,
            fingerprint=fp,
            failure_tags=[],
        )
        norm = math.sqrt(sum(x * x for x in embedding))
        assert norm == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Test: Hash-based embedding (deterministic fallback)
# ---------------------------------------------------------------------------

class TestHashEmbedding:

    def setup_method(self):
        self.chain = _build_chain()

    def test_deterministic(self):
        """Same input always produces same output."""
        e1 = self.chain._hash_embedding("hello world", 768)
        e2 = self.chain._hash_embedding("hello world", 768)
        assert e1 == e2

    def test_correct_dimension(self):
        e = self.chain._hash_embedding("test", 384)
        assert len(e) == 384

    def test_normalised(self):
        e = self.chain._hash_embedding("test", 768)
        norm = math.sqrt(sum(x * x for x in e))
        assert norm == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Test: Time bucket classification
# ---------------------------------------------------------------------------

class TestTimeBucket:

    def test_off_peak_early_morning(self):
        dt = datetime(2026, 3, 15, 3, 0, 0, tzinfo=timezone.utc)
        assert _time_bucket(dt) == "off_peak"

    def test_shoulder_morning(self):
        dt = datetime(2026, 3, 15, 7, 0, 0, tzinfo=timezone.utc)
        assert _time_bucket(dt) == "shoulder"

    def test_peak_midday(self):
        dt = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert _time_bucket(dt) == "peak"

    def test_shoulder_evening(self):
        dt = datetime(2026, 3, 15, 19, 0, 0, tzinfo=timezone.utc)
        assert _time_bucket(dt) == "shoulder"

    def test_off_peak_late_night(self):
        dt = datetime(2026, 3, 15, 23, 0, 0, tzinfo=timezone.utc)
        assert _time_bucket(dt) == "off_peak"
