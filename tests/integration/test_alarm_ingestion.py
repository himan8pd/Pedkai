"""
Integration tests for alarm ingestion endpoint (P1.6).
"""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from backend.app.core.security import create_access_token, Role


@pytest.mark.asyncio
async def test_alarm_ingest_returns_202(client: AsyncClient):
    """Verify POST /api/v1/alarms/ingest returns 202 Accepted."""
    token = create_access_token({"sub": "user1", "role": Role.ADMIN, "tenant_id": "t1"})
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "entity_id": "cell-001",
        "entity_external_id": "ext-cell-001",
        "alarm_type": "LINK_DOWN",
        "severity": "critical",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "oss_vendor",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload, headers=headers)
    
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "event_id" in data
    assert data["tenant_id"] == "t1"
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_alarm_ingest_unauthenticated_returns_401(client: AsyncClient):
    """Verify unauthenticated requests return 401."""
    payload = {
        "entity_id": "cell-001",
        "alarm_type": "LINK_DOWN",
        "severity": "critical",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "oss_vendor",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload)
    
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.asyncio
async def test_alarm_ingest_missing_required_field(client: AsyncClient):
    """Verify missing required fields return 422."""
    token = create_access_token({"sub": "user1", "role": Role.ADMIN, "tenant_id": "t1"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Missing 'severity' field
    payload = {
        "entity_id": "cell-001",
        "alarm_type": "LINK_DOWN",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "oss_vendor",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload, headers=headers)
    
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"


@pytest.mark.asyncio
async def test_alarm_ingest_event_published_to_bus(client: AsyncClient):
    """Verify alarm is published to internal event bus."""
    token = create_access_token({"sub": "user1", "role": Role.ADMIN, "tenant_id": "t2"})
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "entity_id": "site-x",
        "alarm_type": "DEGRADATION",
        "severity": "major",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "snmp",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload, headers=headers)
    
    assert resp.status_code == 202
    
    # Verify event was published (by checking the queue)
    from backend.app.events.bus import get_event_bus
    bus = get_event_bus()
    
    # Queue should be non-empty
    assert bus.qsize() > 0, "Event not published to bus"
    
    # Dequeue and verify
    event = await bus.get()
    assert event.event_type == "alarm_ingested"
    assert event.tenant_id == "t2"
    assert event.alarm_type == "DEGRADATION"
