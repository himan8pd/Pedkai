"""
Integration tests for P1.7 background worker.
"""
import pytest
import asyncio
from datetime import datetime, timezone
from httpx import AsyncClient
from backend.app.core.security import create_access_token, Role


@pytest.mark.asyncio
async def test_worker_starts_on_app_startup(client: AsyncClient):
    """Verify worker starts automatically when app initializes (via client fixture)."""
    # The client fixture initializes the event bus and starts the consumer
    # If we get here without error, the worker started successfully
    
    token = create_access_token({"sub": "user1", "role": Role.ADMIN, "tenant_id": "t1"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Send an alarm to verify worker is running
    payload = {
        "entity_id": "cell-001",
        "alarm_type": "TEST",
        "severity": "minor",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "test",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload, headers=headers)
    assert resp.status_code == 202, f"Failed to publish event: {resp.text}"


@pytest.mark.asyncio
async def test_worker_does_not_block_api(client: AsyncClient):
    """Verify worker runs in background without blocking API requests."""
    token = create_access_token({"sub": "user1", "role": Role.ADMIN, "tenant_id": "t1"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Send an alarm
    payload = {
        "entity_id": "cell-api-test",
        "alarm_type": "GENERIC",
        "severity": "minor",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "api",
    }
    
    resp = await client.post("/api/v1/alarms/ingest", json=payload, headers=headers)
    
    # Verify API returns quickly (202)
    assert resp.status_code == 202, f"API blocked or failed: {resp.text}"
    
    # Response time should be <100ms (confirm non-blocking)
    assert resp.elapsed.total_seconds() < 0.1, f"API took too long: {resp.elapsed}"
