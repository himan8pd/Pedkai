"""
Tests for the Redis Streams-backed EventBus with asyncio.Queue fallback.

All tests run in fallback mode (no Redis required). REDIS_URL must NOT be set
in the environment when running these tests, which is the default for CI/local dev.

Run with:
    pytest tests/test_event_bus.py -v --noconftest

Or via the project Makefile / CI which sets SECRET_KEY automatically.
"""
import asyncio
import os
import uuid

import pytest

# Provide the minimum env vars required by backend.app.core.config.Settings so
# that importing from backend.app.services.event_bus (which triggers the services
# package __init__.py → DecisionTraceRepository → database → Settings) does not
# blow up with a ValidationError.  These values are never used by the event bus
# code under test — they only satisfy Pydantic Settings field requirements.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-event-bus-tests")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_event_bus_stub.db")

# Ensure REDIS_URL is not set so tests use the fallback asyncio.Queue path
os.environ.pop("REDIS_URL", None)

from backend.app.services.event_bus import Event, EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> EventBus:
    """Return a fresh EventBus instance (no Redis URL → fallback mode)."""
    bus = EventBus()
    assert bus._redis_url is None, "REDIS_URL must not be set for these tests"
    return bus


async def _drain(bus: EventBus, event_type: str, tenant_id: str, count: int) -> list[Event]:
    """Pull exactly `count` events from the fallback queue synchronously."""
    queue_key = f"{tenant_id}:{event_type}"
    # Pre-populate if needed so the queue exists
    if queue_key not in bus._fallback_queues:
        bus._fallback_queues[queue_key] = asyncio.Queue()
    events = []
    for _ in range(count):
        event = bus._fallback_queues[queue_key].get_nowait()
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_subscribe_delivers_correct_payload():
    """publish() then subscribe() delivers the event with the correct payload."""
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "anomaly.detected"
    payload = {"alarm_id": "A1", "severity": "critical", "cell": "site-99"}

    event_id = await bus.publish(event_type, payload, tenant_id)
    assert event_id.startswith("fallback-")

    # subscribe() is an async generator — pull one item with a timeout guard
    received: list[Event] = []

    async def _collect_one():
        async for event in bus.subscribe(event_type, "grp", "c1", tenant_id=str(tenant_id)):
            received.append(event)
            return  # stop after first event

    await asyncio.wait_for(_collect_one(), timeout=2)

    assert len(received) == 1
    evt = received[0]
    assert evt.event_type == event_type
    assert evt.tenant_id == str(tenant_id)
    assert evt.payload == payload
    assert evt.event_id == event_id


@pytest.mark.asyncio
async def test_fallback_mode_uses_asyncio_queue():
    """In fallback mode the bus uses asyncio.Queue (no Redis client is created)."""
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "sleeping_cell.detected"

    await bus.publish(event_type, {"cell": "X"}, tenant_id)

    queue_key = f"{tenant_id}:{event_type}"
    assert queue_key in bus._fallback_queues
    assert isinstance(bus._fallback_queues[queue_key], asyncio.Queue)
    # Verify no Redis client was instantiated
    assert bus._redis_client is None


@pytest.mark.asyncio
async def test_get_pending_count_returns_correct_count_after_five_publishes():
    """get_pending_count() reflects the number of unconsumed events in fallback mode."""
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "operator.feedback_received"

    for i in range(5):
        await bus.publish(event_type, {"index": i}, tenant_id)

    count = await bus.get_pending_count(event_type, "grp", tenant_id=str(tenant_id))
    assert count == 5


@pytest.mark.asyncio
async def test_acknowledged_events_not_redelivered_in_fallback():
    """
    In fallback mode, once an event is consumed from the Queue it is gone
    (the Queue has no redelivery semantics). This test verifies that after
    consuming an event the queue size decreases, matching the contract that
    acknowledged/consumed events are not re-served.
    """
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "dark_graph.divergence_found"

    # Publish two events
    await bus.publish(event_type, {"graph": "G1"}, tenant_id)
    await bus.publish(event_type, {"graph": "G2"}, tenant_id)

    queue_key = f"{tenant_id}:{event_type}"
    assert bus._fallback_queues[queue_key].qsize() == 2

    # Consume one event via subscribe
    consumed: list[Event] = []

    async def _consume_one():
        async for event in bus.subscribe(event_type, "grp", "c1", tenant_id=str(tenant_id)):
            consumed.append(event)
            # In fallback mode acknowledge is a no-op (no Redis), but calling it
            # must not raise.
            await bus.acknowledge(event_type, "grp", event.event_id, tenant_id=str(tenant_id))
            return

    await asyncio.wait_for(_consume_one(), timeout=2)

    assert len(consumed) == 1
    # Only one event should remain in the queue
    assert bus._fallback_queues[queue_key].qsize() == 1


@pytest.mark.asyncio
async def test_multiple_event_types_are_isolated():
    """Events published to different event types do not appear in each other's queues."""
    bus = _make_bus()
    tenant_id = uuid.uuid4()

    await bus.publish("anomaly.detected", {"x": 1}, tenant_id)
    await bus.publish("sleeping_cell.detected", {"y": 2}, tenant_id)

    key_a = f"{tenant_id}:anomaly.detected"
    key_s = f"{tenant_id}:sleeping_cell.detected"

    assert bus._fallback_queues[key_a].qsize() == 1
    assert bus._fallback_queues[key_s].qsize() == 1

    event_a = bus._fallback_queues[key_a].get_nowait()
    event_s = bus._fallback_queues[key_s].get_nowait()

    assert event_a.payload == {"x": 1}
    assert event_s.payload == {"y": 2}


@pytest.mark.asyncio
async def test_multiple_tenants_are_isolated():
    """Events for different tenants are stored in separate queues."""
    bus = _make_bus()
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    event_type = "abeyance.snap_occurred"

    await bus.publish(event_type, {"tenant": "A"}, tenant_a)
    await bus.publish(event_type, {"tenant": "B"}, tenant_b)

    key_a = f"{tenant_a}:{event_type}"
    key_b = f"{tenant_b}:{event_type}"

    assert bus._fallback_queues[key_a].qsize() == 1
    assert bus._fallback_queues[key_b].qsize() == 1

    evt_a = bus._fallback_queues[key_a].get_nowait()
    evt_b = bus._fallback_queues[key_b].get_nowait()

    assert evt_a.payload["tenant"] == "A"
    assert evt_b.payload["tenant"] == "B"
