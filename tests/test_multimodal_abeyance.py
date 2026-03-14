"""Tests for multi-modal Abeyance Memory matching (TASK-306)."""
import os
import tempfile
import numpy as np
import pytest
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")
os.environ["COLD_STORAGE_BASE_PATH"] = tempfile.mkdtemp(prefix="pedkai_modal_test_")

from backend.app.services.abeyance.telemetry_aligner import TelemetryAligner, AnomalyFinding
from backend.app.services.abeyance.cold_storage import AbeyanceColdStorage, AbeyanceFragment


@pytest.fixture
def aligner():
    return TelemetryAligner()  # no external embedding service; uses hash fallback


@pytest.fixture
def anomaly(request):
    return AnomalyFinding(
        entity_id="CELL-001",
        tenant_id="test-tenant",
        domain="RAN",
        kpi_name="prb_utilisation",
        value=95.5,
        z_score=3.2,
        timestamp=datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
        affected_metrics=["prb_utilisation", "throughput_dl"],
        neighbour_count=3,
        neighbour_summary="high PRB neighbours"
    )


def test_anomaly_to_text_contains_entity_id(aligner, anomaly):
    text = aligner.anomaly_to_text(anomaly)
    assert "CELL-001" in text
    assert "prb_utilisation" in text
    assert "3.2" in text


def test_anomaly_to_text_contains_domain(aligner, anomaly):
    text = aligner.anomaly_to_text(anomaly)
    assert "RAN" in text


def test_embed_anomaly_returns_vector(aligner, anomaly):
    emb = aligner.embed_anomaly(anomaly)
    assert isinstance(emb, np.ndarray)
    assert len(emb) > 0


def test_embed_anomaly_is_deterministic(aligner, anomaly):
    emb1 = aligner.embed_anomaly(anomaly)
    emb2 = aligner.embed_anomaly(anomaly)
    np.testing.assert_array_almost_equal(emb1, emb2)


def test_store_anomaly_fragment_creates_fragment(aligner, anomaly):
    fragment = aligner.store_anomaly_fragment(anomaly)
    assert fragment.metadata.get("modality") == "telemetry"
    assert fragment.tenant_id == "test-tenant"
    assert len(fragment.embedding) > 0


def test_telemetry_fragment_retrievable_by_similarity(aligner, anomaly):
    """Store a telemetry fragment, then search cold storage and find it."""
    storage = AbeyanceColdStorage()
    fragment = aligner.store_anomaly_fragment(anomaly, storage=storage)

    # Search with the fragment's own embedding
    query = np.array(fragment.embedding)
    results = storage.search_cold(query, top_k=1, tenant_id=anomaly.tenant_id)

    assert len(results) >= 1
    # Cosine similarity with itself should be very high
    result_emb = np.array(results[0].embedding)
    cos_sim = float(np.dot(query, result_emb) / (np.linalg.norm(query) * np.linalg.norm(result_emb) + 1e-10))
    assert cos_sim > 0.99


def test_fragment_metadata_has_text_description(aligner, anomaly):
    fragment = aligner.store_anomaly_fragment(anomaly)
    assert "text_description" in fragment.metadata
    assert len(fragment.metadata["text_description"]) > 50
