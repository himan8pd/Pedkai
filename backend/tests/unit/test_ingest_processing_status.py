"""Unit tests for BLK-01: surface snap-evaluation failures in the ingest response.

The `/api/v1/abeyance/ingest` endpoint always stores the enriched fragment
(HTTP 201) but post-storage evaluation (snap engine + cluster detection) is
best-effort. These tests assert that the response now reports the outcome of
that evaluation via a `processing` block, for both the happy path and a forced
snap-engine failure.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import backend.app.api.abeyance as abeyance_api
from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, oauth2_scheme, User
from backend.app.main import app


def _make_fragment() -> SimpleNamespace:
    """A minimal object that satisfies AbeyanceFragmentResponse validation."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="tenant-test",
        source_type="ALARM",
        raw_content="link down on card 3",
        extracted_entities=[],
        topological_neighbourhood={},
        operational_fingerprint={},
        failure_mode_tags=[],
        temporal_context={},
        event_timestamp=now,
        ingestion_timestamp=now,
        base_relevance=1.0,
        current_decay_score=1.0,
        near_miss_count=0,
        snap_status="ABEYANCE",
        snapped_hypothesis_id=None,
        source_ref=None,
        created_at=now,
        mask_semantic=True,
        mask_topological=True,
        mask_operational=True,
    )


def _build_client(snap_evaluate: AsyncMock) -> TestClient:
    """Wire dependency overrides and injected mock services for the router."""
    # Fake DB session: only `flush` is awaited in the endpoint.
    fake_db = AsyncMock()
    fake_db.flush = AsyncMock()

    fragment = _make_fragment()

    enrichment = SimpleNamespace(enrich=AsyncMock(return_value=fragment))
    snap_engine = SimpleNamespace(evaluate=snap_evaluate)
    accumulation = SimpleNamespace(detect_and_evaluate_clusters=AsyncMock())

    # Inject the service singleton directly so the real factory (which needs a
    # DB / redis) is never invoked.
    abeyance_api._services = {
        "enrichment_v3": enrichment,
        "snap_engine_v3": snap_engine,
        "accumulation_graph": accumulation,
    }

    app.dependency_overrides[get_db] = lambda: fake_db
    # Bypass the OAuth2 bearer-token extraction (would otherwise 401), then
    # override get_current_user to return an authorised principal.
    app.dependency_overrides[oauth2_scheme] = lambda: "test-token"
    app.dependency_overrides[get_current_user] = lambda: User(
        username="tester",
        role="admin",
        tenant_id="tenant-test",
        scopes=["incident:read"],
    )

    return TestClient(app)


def _payload() -> dict:
    return {"content": "link down on card 3", "source_type": "ALARM"}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()
    abeyance_api._services = None


def test_ingest_snap_failure_reports_failed_status():
    """A forced snap-engine exception yields 201 with processing.snap_evaluation == failed."""
    failing_evaluate = AsyncMock(side_effect=RuntimeError("boom in snap engine"))
    client = _build_client(failing_evaluate)

    resp = client.post("/api/v1/abeyance/ingest", json=_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Existing fragment fields are still present.
    assert body["tenant_id"] == "tenant-test"
    assert body["source_type"] == "ALARM"
    # New processing block.
    assert body["processing"]["snap_evaluation"] == "failed"
    assert body["processing"]["cluster_detection"] == "ok"
    assert body["processing"]["errors"]
    assert any("boom in snap engine" in e for e in body["processing"]["errors"])


def test_ingest_happy_path_reports_ok_status():
    """The happy path yields 201 with both stages == ok and no errors."""
    ok_evaluate = AsyncMock(return_value={"snaps": [], "near_misses": []})
    client = _build_client(ok_evaluate)

    resp = client.post("/api/v1/abeyance/ingest", json=_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["processing"]["snap_evaluation"] == "ok"
    assert body["processing"]["cluster_detection"] == "ok"
    assert body["processing"]["errors"] == []
