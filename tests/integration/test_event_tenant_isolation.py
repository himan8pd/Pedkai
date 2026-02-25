import asyncio

import pytest


async def test_event_tenant_isolation(client):
    """
    Integration test for event tenant isolation (P1.9):
    1. Post an alarm as tenant_A -> handler should receive tenant_A
    2. Post an alarm as tenant_B -> handler should receive tenant_B
    Ensures cross-tenant leakage does not occur.
    """
    from backend.app.main import app
    from backend.app.workers.handlers import register_handler
    from backend.app.core import security
    processed = []


    async def capture_handler(event):
        processed.append(event)


    # Register a test handler that captures processed events
    register_handler("alarm_ingested", capture_handler)

    # Ensure the background consumer is running (start_event_consumer returns a Task)
    from backend.app.workers.consumer import start_event_consumer
    consumer_task = await start_event_consumer()
    # Give consumer a moment to spin up
    await asyncio.sleep(0.05)

    # Fake current_user for tenant A
    async def fake_user_a(security_scopes=None, token=None):
        from backend.app.core.security import User, TMF642_WRITE

        return User(username="alice", role="operator", scopes=[TMF642_WRITE], tenant_id="tenant_A")


    # Fake current_user for tenant B
    async def fake_user_b(security_scopes=None, token=None):
        from backend.app.core.security import User, TMF642_WRITE

        return User(username="bob", role="operator", scopes=[TMF642_WRITE], tenant_id="tenant_B")


    # Override dependency to tenant A and ingest one alarm
    app.dependency_overrides[security.get_current_user] = fake_user_a

    body_a = {
        "entity_id": "00000000-0000-0000-0000-000000000001",
        "entity_external_id": "ext-1",
        "alarm_type": "LINK_DOWN",
        "severity": "critical",
        "raised_at": "2026-02-23T00:00:00Z",
        "source_system": "test",
    }

    resp = await client.post("/api/v1/alarms/ingest", json=body_a)
    assert resp.status_code == 202

    # Wait for the consumer to process the event
    for _ in range(50):
        if processed:
            break
        await asyncio.sleep(0.05)

    assert processed, "No events were processed for tenant_A"
    assert getattr(processed[0], "tenant_id", None) == "tenant_A"

    # Switch to tenant B and ingest a second alarm
    app.dependency_overrides[security.get_current_user] = fake_user_b

    body_b = body_a.copy()
    body_b["entity_id"] = "00000000-0000-0000-0000-000000000002"

    resp = await client.post("/api/v1/alarms/ingest", json=body_b)
    assert resp.status_code == 202

    for _ in range(50):
        if len(processed) >= 2:
            break
        await asyncio.sleep(0.05)

    assert len(processed) >= 2, "Second event not processed"
    assert getattr(processed[1], "tenant_id", None) == "tenant_B"

    # Cleanup dependency override and stop consumer
    app.dependency_overrides.pop(security.get_current_user, None)
    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
