"""
Production-equivalent telemetry message schemas.

These schemas define the canonical JSON structure for Kafka messages.
Both the Parquet replay producer and future live telemetry sources
must emit messages conforming to these schemas.

No replay-specific fields are permitted — downstream consumers must
remain completely unaware of the telemetry source.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def row_to_message(row: pd.Series, timestamp_col: str = "timestamp") -> dict[str, Any]:
    """
    Convert a Pandas row to a production-equivalent JSON message.

    Handles:
    - NaN/NaT → null
    - Timestamps → ISO 8601 strings (UTC)
    - numpy types → native Python types
    - Boolean columns preserved

    This is the single serialization point for all telemetry messages.
    """
    msg: dict[str, Any] = {}
    for key, value in row.items():
        if pd.isna(value):
            msg[key] = None
        elif isinstance(value, (pd.Timestamp, datetime)):
            # Always emit UTC ISO 8601
            if hasattr(value, "tzinfo") and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            msg[key] = value.isoformat()
        elif isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                msg[key] = None
            else:
                msg[key] = value
        elif hasattr(value, "item"):
            # numpy scalar → Python native
            msg[key] = value.item()
        elif isinstance(value, bool):
            msg[key] = value
        else:
            msg[key] = value
    return msg


def make_kafka_key(row: pd.Series, entity_col: str) -> bytes | None:
    """
    Create a Kafka message key from the entity identifier.

    Using entity ID as the key ensures all messages for the same entity
    land on the same Kafka partition, preserving per-entity ordering.
    """
    entity_id = row.get(entity_col)
    if entity_id and not pd.isna(entity_id):
        return str(entity_id).encode("utf-8")
    return None
