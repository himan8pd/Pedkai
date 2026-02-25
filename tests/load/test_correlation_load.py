"""
Load tests for alarm correlation service (P1.4).

Verifies that the O(n log n) optimized algorithm processes
5000 alarms in < 5 seconds (previously O(n²) ~30 seconds).
"""
import pytest
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from backend.app.services.alarm_correlation import AlarmCorrelationService
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_correlation_5000_alarms_under_5_seconds():
    """
    Load test: Process 5000 alarms in < 5 seconds.

    Simulates a realistic scenario with:
    - 1000 unique network entities
    - 5 alarm types per entity
    - Temporal distribution over 10-minute window
    """
    # Create a mock session factory (not actually used in correlate_alarms)
    session_factory = async_sessionmaker()
    service = AlarmCorrelationService(session_factory)

    # Generate 5000 realistic test alarms
    alarms = generate_realistic_alarms(count=5000, num_entities=1000)

    # Measure correlation time
    start_time = time.time()
    clusters = service.correlate_alarms(alarms)
    elapsed_seconds = time.time() - start_time

    print(f"\nLoad Test Results:")
    print(f"  Alarms: {len(alarms)}")
    print(f"  Clusters: {len(clusters)}")
    print(f"  Elapsed: {elapsed_seconds:.3f}s")
    print(f"  Avg per alarm: {elapsed_seconds / len(alarms) * 1000:.2f}ms")

    # Performance requirements
    assert elapsed_seconds < 5.0, f"Expected < 5s, got {elapsed_seconds:.3f}s"
    assert len(clusters) > 0, "Should create at least one cluster"
    assert sum(c["alarm_count"] for c in clusters) == len(alarms), "All alarms should be clustered"


def test_correlation_with_high_temporal_clustering():
    """
    Load test: 5000 alarms with high temporal clustering.

    Tests the case where many alarms fall within the same temporal window,
    ensuring the algorithm still performs well with deep clusters.
    """
    session_factory = async_sessionmaker()
    service = AlarmCorrelationService(session_factory)

    # 5000 alarms all within same 5-minute window over 100 entities
    base_time = datetime.now(timezone.utc)
    alarms = []
    for i in range(5000):
        entity_id = f"entity-{i % 100}"
        alarm_type = f"type-{i % 5}"
        alarm_time = base_time + timedelta(seconds=(i % 300))  # All within 5-min window

        alarms.append({
            "id": str(uuid.uuid4()),
            "entity_id": entity_id,
            "alarm_type": alarm_type,
            "severity": ["minor", "major", "critical"][i % 3],
            "raised_at": alarm_time.isoformat(),
            "source_system": "oss_test",
        })

    start_time = time.time()
    clusters = service.correlate_alarms(alarms)
    elapsed_seconds = time.time() - start_time

    print(f"\nHigh Clustering Load Test:")
    print(f"  Alarms: {len(alarms)}")
    print(f"  Clusters: {len(clusters)}")
    print(f"  Elapsed: {elapsed_seconds:.3f}s")
    print(f"  Avg cluster size: {len(alarms) / len(clusters):.1f}")

    assert elapsed_seconds < 5.0, f"Expected < 5s, got {elapsed_seconds:.3f}s"
    # With high clustering, should see fewer clusters than entities
    assert len(clusters) < 500, "Should merge temporally-overlapping alarms"


def test_correlation_mixed_scalability():
    """
    Load test: Mixed scenario with varying alarm distributions.

    Tests realistic distribution:
    - 30% isolated alarms (single cluster)
    - 50% small bunches (2-5 per cluster)
    - 20% large clusters (10+ per cluster)
    """
    session_factory = async_sessionmaker()
    service = AlarmCorrelationService(session_factory)

    alarms = generate_mixed_distribution_alarms(count=5000)

    start_time = time.time()
    clusters = service.correlate_alarms(alarms)
    elapsed_seconds = time.time() - start_time

    print(f"\nMixed Distribution Load Test:")
    print(f"  Alarms: {len(alarms)}")
    print(f"  Clusters: {len(clusters)}")
    print(f"  Elapsed: {elapsed_seconds:.3f}s")

    assert elapsed_seconds < 5.0, f"Expected < 5s, got {elapsed_seconds:.3f}s"


def generate_realistic_alarms(count: int = 5000, num_entities: int = 1000) -> List[Dict[str, Any]]:
    """
    Generate realistic alarm data for load testing.

    Distribution:
    - 1000 unique entities
    - 5 alarm types
    - Temporal spread over 10-minute window
    - Severity distribution matching real systems
    """
    base_time = datetime.now(timezone.utc)
    severity_dist = ["minor"] * 50 + ["major"] * 30 + ["critical"] * 20

    alarms = []
    for i in range(count):
        entity_idx = i % num_entities
        alarm_type_idx = (i // num_entities) % 5
        seconds_offset = (i * 120) % 600  # Spread over 10 minutes

        alarms.append({
            "id": str(uuid.uuid4()),
            "entity_id": f"entity-{entity_idx:04d}",
            "entity_type": ["CELL", "NODE", "SITE", "SECTOR"][entity_idx % 4],
            "alarm_type": f"alarm_type_{alarm_type_idx}",
            "severity": severity_dist[i % len(severity_dist)],
            "raised_at": (base_time + timedelta(seconds=seconds_offset)).isoformat(),
            "source_system": ["oss_vendor", "snmp", "api"][i % 3],
            "external_id": f"ext-{i}",
        })

    return alarms


def generate_mixed_distribution_alarms(count: int = 5000) -> List[Dict[str, Any]]:
    """
    Generate alarms with mixed clustering characteristics.

    30% isolated, 50% small bunches, 20% large clusters.
    """
    base_time = datetime.now(timezone.utc)
    alarms = []

    iso_count = int(count * 0.30)
    small_count = int(count * 0.50)
    large_count = count - iso_count - small_count

    # 30% isolated alarms
    for i in range(iso_count):
        alarms.append({
            "id": str(uuid.uuid4()),
            "entity_id": f"iso-entity-{i}",  # Each differs
            "alarm_type": "isolated_type",
            "severity": "minor",
            "raised_at": (base_time + timedelta(seconds=i)).isoformat(),
            "source_system": "api",
        })

    # 50% small bunches (2-5 per cluster)
    entity_bunch_base = iso_count
    i = 0
    while i < small_count:
        bunch_size = min(5, small_count - i)
        entity_id = f"bunch-entity-{entity_bunch_base + i // bunch_size}"
        for j in range(bunch_size):
            if i < small_count:
                alarms.append({
                    "id": str(uuid.uuid4()),
                    "entity_id": entity_id,
                    "alarm_type": f"bunch_type_{i % 3}",
                    "severity": "major",
                    "raised_at": (base_time + timedelta(seconds=i + j)).isoformat(),
                    "source_system": "oss_vendor",
                })
                i += 1

    # 20% large clusters (2-10 alarms per type/entity)
    large_entity_count = 100
    large_per_entity = large_count // large_entity_count
    for entity_idx in range(large_entity_count):
        entity_id = f"large-entity-{entity_idx}"
        for j in range(large_per_entity):
            alarms.append({
                "id": str(uuid.uuid4()),
                "entity_id": entity_id,
                "alarm_type": f"large_type_{j % 3}",
                "severity": ["minor", "major"][j % 2],
                "raised_at": (base_time + timedelta(
                    seconds=int(600 / large_entity_count) * entity_idx + j
                )).isoformat(),
                "source_system": "snmp",
            })

    return alarms
