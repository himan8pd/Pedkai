"""
Decision trace API endpoint tests.

Tests the /api/v1/decisions/* routes.
Uses the standard `client` fixture (mock auth) since the decision API
does not enforce explicit auth in route signatures.
"""
import pytest
import uuid
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# POST /decisions — create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_decision_trace(client: AsyncClient, db_session: AsyncSession):
    """Create a decision trace returns 201."""
    payload = {
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "LINK_DOWN on site-x",
        "context": {},
        "decision_summary": "Reroute traffic via site-y",
        "tradeoff_rationale": "Risk of congestion vs total outage",
        "action_taken": "BGP reroute executed",
        "decision_maker": "autobot",
    }
    resp = await client.post("/api/v1/decisions", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trigger_type"] == "alarm"
    assert body["decision_summary"] == "Reroute traffic via site-y"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_decision_trace_idempotent(client: AsyncClient, db_session: AsyncSession):
    """Duplicate trigger_id + tenant_id + trigger_type returns existing trace."""
    trigger_id = str(uuid.uuid4())
    payload = {
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_id": trigger_id,
        "trigger_description": "Idempotent test alarm",
        "context": {},
        "decision_summary": "Ignore — known flap",
        "tradeoff_rationale": "None",
        "action_taken": "Suppressed",
        "decision_maker": "autobot",
    }
    resp1 = await client.post("/api/v1/decisions", json=payload)
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    resp2 = await client.post("/api/v1/decisions", json=payload)
    # Idempotent: same ID returned
    assert resp2.json()["id"] == id1


# ---------------------------------------------------------------------------
# GET /decisions — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_decisions(client: AsyncClient, db_session: AsyncSession):
    """List decisions returns array for tenant."""
    # Create one first
    await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "Test alarm",
        "context": {},
        "decision_summary": "Test summary",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
    })
    resp = await client.get("/api/v1/decisions?tenant_id=test-tenant")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_decisions_filter_by_domain(client: AsyncClient, db_session: AsyncSession):
    """Filter decisions by domain."""
    await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "anomaly",
        "trigger_description": "KPI anomaly",
        "context": {},
        "decision_summary": "Domain filtered",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
        "domain": "capacity",
    })
    resp = await client.get("/api/v1/decisions?tenant_id=test-tenant&domain=capacity")
    assert resp.status_code == 200
    data = resp.json()
    assert all(d.get("domain") == "capacity" for d in data)


# ---------------------------------------------------------------------------
# GET /decisions/{id} — get by ID
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_decision_by_id(client: AsyncClient, db_session: AsyncSession):
    """Retrieve a specific decision by ID."""
    create_resp = await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "Lookup test",
        "context": {},
        "decision_summary": "Find me",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
    })
    decision_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/decisions/{decision_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == decision_id


@pytest.mark.asyncio
async def test_get_decision_not_found(client: AsyncClient, db_session: AsyncSession):
    """Non-existent ID returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/decisions/{fake_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /decisions/{id} — update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_decision(client: AsyncClient, db_session: AsyncSession):
    """Update a decision trace's tags (one of the updatable fields)."""
    create_resp = await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "Update test",
        "context": {},
        "decision_summary": "Before update",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
    })
    decision_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/decisions/{decision_id}",
        json={"tags": ["critical", "network"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tags"] == ["critical", "network"]


# ---------------------------------------------------------------------------
# POST /decisions/{id}/upvote and /downvote — RLHF feedback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upvote_decision(client: AsyncClient, db_session: AsyncSession):
    """Upvote a decision returns success."""
    create_resp = await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "Vote test",
        "context": {},
        "decision_summary": "Voteable",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
    })
    decision_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/decisions/{decision_id}/upvote")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "upvoted"


@pytest.mark.asyncio
async def test_downvote_decision(client: AsyncClient, db_session: AsyncSession):
    """Downvote a decision returns success."""
    create_resp = await client.post("/api/v1/decisions", json={
        "tenant_id": "test-tenant",
        "trigger_type": "alarm",
        "trigger_description": "Down test",
        "context": {},
        "decision_summary": "Thumbs down",
        "tradeoff_rationale": "None",
        "action_taken": "None",
        "decision_maker": "autobot",
    })
    decision_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/decisions/{decision_id}/downvote")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "downvoted"


@pytest.mark.asyncio
async def test_upvote_nonexistent(client: AsyncClient, db_session: AsyncSession):
    """Upvoting a non-existent decision returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/api/v1/decisions/{fake_id}/upvote")
    assert resp.status_code == 404
