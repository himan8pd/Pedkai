"""
Redis Streams-backed event bus with asyncio.Queue fallback for local dev.

Usage:
    bus = EventBus()
    event_id = await bus.publish("anomaly.detected", payload, tenant_id)
    async for event in bus.subscribe("anomaly.detected", "my-group", "consumer-1"):
        process(event)
        await bus.acknowledge(...)
"""
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional
from uuid import UUID

@dataclass
class Event:
    event_id: str
    event_type: str
    payload: dict
    tenant_id: str
    timestamp: datetime

class EventBus:
    # 5 supported event types
    EVENT_TYPES = [
        "anomaly.detected",
        "sleeping_cell.detected",
        "dark_graph.divergence_found",
        "operator.feedback_received",
        "abeyance.snap_occurred",
    ]

    def __init__(self):
        self._redis_url = os.environ.get("REDIS_URL")
        self._fallback_queues: dict[str, asyncio.Queue] = {}
        self._redis_client = None

    async def _get_redis(self):
        if self._redis_url and self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(self._redis_url)
            except ImportError:
                self._redis_client = None
        return self._redis_client

    def _stream_key(self, event_type: str, tenant_id: str) -> str:
        return f"events:{tenant_id}:{event_type}"

    async def publish(self, event_type: str, payload: dict, tenant_id: UUID) -> str:
        tenant_str = str(tenant_id)
        r = await self._get_redis()
        if r:
            # Redis Streams XADD
            stream_key = self._stream_key(event_type, tenant_str)
            event_data = {
                "event_type": event_type,
                "tenant_id": tenant_str,
                "payload": json.dumps(payload),
                "timestamp": datetime.utcnow().isoformat(),
            }
            event_id = await r.xadd(stream_key, event_data)
            return event_id.decode() if isinstance(event_id, bytes) else str(event_id)
        else:
            # Fallback: asyncio.Queue
            queue_key = f"{tenant_str}:{event_type}"
            if queue_key not in self._fallback_queues:
                self._fallback_queues[queue_key] = asyncio.Queue()
            event_id = f"fallback-{datetime.utcnow().timestamp()}"
            event = Event(
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                tenant_id=tenant_str,
                timestamp=datetime.utcnow(),
            )
            await self._fallback_queues[queue_key].put(event)
            return event_id

    async def subscribe(self, event_type: str, consumer_group: str, consumer_name: str, tenant_id: str = "*") -> AsyncIterator[Event]:
        """Yields events from the stream."""
        r = await self._get_redis()
        if r:
            stream_key = self._stream_key(event_type, tenant_id)
            # Ensure consumer group exists
            try:
                await r.xgroup_create(stream_key, consumer_group, id="0", mkstream=True)
            except Exception:
                pass  # Group already exists
            while True:
                results = await r.xreadgroup(
                    consumer_group, consumer_name,
                    {stream_key: ">"}, count=10, block=1000
                )
                for _, messages in results:
                    for msg_id, data in messages:
                        yield Event(
                            event_id=msg_id.decode(),
                            event_type=data.get(b"event_type", b"").decode(),
                            payload=json.loads(data.get(b"payload", b"{}")),
                            tenant_id=data.get(b"tenant_id", b"").decode(),
                            timestamp=datetime.fromisoformat(data.get(b"timestamp", b"").decode()),
                        )
        else:
            queue_key = f"{tenant_id}:{event_type}"
            if queue_key not in self._fallback_queues:
                self._fallback_queues[queue_key] = asyncio.Queue()
            while True:
                event = await self._fallback_queues[queue_key].get()
                yield event

    async def acknowledge(self, event_type: str, consumer_group: str, event_id: str, tenant_id: str = "*") -> None:
        r = await self._get_redis()
        if r:
            stream_key = self._stream_key(event_type, tenant_id)
            await r.xack(stream_key, consumer_group, event_id)

    async def get_pending_count(self, event_type: str, consumer_group: str, tenant_id: str = "*") -> int:
        r = await self._get_redis()
        if r:
            stream_key = self._stream_key(event_type, tenant_id)
            try:
                info = await r.xpending(stream_key, consumer_group)
                return info.get("pending", 0) if isinstance(info, dict) else info[0]
            except Exception:
                return 0
        else:
            queue_key = f"{tenant_id}:{event_type}"
            return self._fallback_queues.get(queue_key, asyncio.Queue()).qsize()


# Singleton
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
