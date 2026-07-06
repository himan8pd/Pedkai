"""Unit test for BLK-02 — fragment-bridge queue-drop alerting.

Verifies that when the bounded asyncio queue is full, enqueue_alarm:
  * increments the dropped counter for each dropped event, and
  * emits exactly one ERROR log record per DROP_LOG_EVERY window, and
  * exposes the counter via stats().
"""

import logging

import pytest

from backend.app.telemetry.fragment_bridge import TelemetryFragmentBridge


@pytest.mark.asyncio
async def test_enqueue_alarm_drops_are_counted_and_logged(caplog):
    # maxsize=1: first enqueue fills the queue, next two are dropped.
    bridge = TelemetryFragmentBridge(queue_size=1)

    alarm = {"tenant_id": "t1", "entity_id": "e1", "alarm_id": "a1"}

    with caplog.at_level(logging.ERROR, logger="backend.app.telemetry.fragment_bridge"):
        bridge.enqueue_alarm(alarm)  # accepted (queue now full)
        bridge.enqueue_alarm(alarm)  # dropped -> _dropped == 1 -> logs
        bridge.enqueue_alarm(alarm)  # dropped -> _dropped == 2 -> no log

    stats = bridge.stats()
    assert stats["dropped"] == 2
    assert stats["queue_size"] == 1

    error_records = [
        r for r in caplog.records if r.levelno == logging.ERROR
    ]
    assert len(error_records) == 1
    assert "queue full" in error_records[0].getMessage()
