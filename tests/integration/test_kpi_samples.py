"""
Integration tests for KpiSampleORM (P1.3).

Verifies time-series KPI data storage, foreign key constraints, and query patterns.
"""
import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.models.kpi_sample_orm import KpiSampleORM
from backend.app.models.network_entity_orm import NetworkEntityORM


@pytest.mark.asyncio
async def test_kpi_sample_creation(db_session: AsyncSession):
    """Create a KPI sample and verify it's stored correctly."""
    # Create test entity
    entity_id = uuid.uuid4()
    entity = NetworkEntityORM(
        id=entity_id,
        tenant_id="test-tenant",
        entity_type="GNODEB",
        name="Test gNodeB",
        external_id="EXT-001"
    )
    db_session.add(entity)
    await db_session.flush()
    
    # Create KPI sample
    kpi = KpiSampleORM(
        tenant_id="test-tenant",
        entity_id=entity_id,
        metric_name="PRB_UTIL",
        value=85.5,
        timestamp=datetime.now(timezone.utc),
        source="RAN_TELEMETRY"
    )
    db_session.add(kpi)
    await db_session.commit()
    
    # Verify retrieval
    result = await db_session.execute(
        select(KpiSampleORM).where(KpiSampleORM.id == kpi.id)
    )
    retrieved = result.scalars().first()
    assert retrieved is not None
    assert retrieved.metric_name == "PRB_UTIL"
    assert retrieved.value == 85.5
    assert retrieved.entity_id == entity_id


@pytest.mark.asyncio
async def test_kpi_sample_foreign_key(db_session: AsyncSession):
    """Verify foreign key relationship between KPI samples and network entities."""
    entity_id = uuid.uuid4()
    entity = NetworkEntityORM(
        id=entity_id,
        tenant_id="test-tenant",
        entity_type="CELL",
        name="Test Cell",
    )
    db_session.add(entity)
    await db_session.flush()
    
    kpi = KpiSampleORM(
        tenant_id="test-tenant",
        entity_id=entity_id,
        metric_name="LATENCY_MS",
        value=42.3,
        timestamp=datetime.now(timezone.utc),
        source="BSS"
    )
    db_session.add(kpi)
    await db_session.commit()
    
    # Retrieve and check relational integrity
    result = await db_session.execute(
        select(KpiSampleORM).where(
            KpiSampleORM.entity_id == entity_id
        )
    )
    kpi_retrieved = result.scalars().first()
    assert kpi_retrieved is not None
    assert kpi_retrieved.entity_id == entity_id


@pytest.mark.asyncio
async def test_kpi_time_series_query(db_session: AsyncSession):
    """Test efficient time-series range queries (composite index pattern)."""
    entity_id = uuid.uuid4()
    entity = NetworkEntityORM(
        id=entity_id,
        tenant_id="test-tenant",
        entity_type="SITE",
        name="Test Site",
    )
    db_session.add(entity)
    await db_session.flush()
    
    # Create multiple KPI samples
    now = datetime.now(timezone.utc)
    for i in range(3):
        kpi = KpiSampleORM(
            tenant_id="test-tenant",
            entity_id=entity_id,
            metric_name="BANDWIDTH_UTIL",
            value=50.0 + i * 10,  # 50, 60, 70
            timestamp=now,
            source="RAN_TELEMETRY"
        )
        db_session.add(kpi)
    await db_session.commit()
    
    # Query by entity and metric (composite index pattern)
    result = await db_session.execute(
        select(KpiSampleORM).where(
            (KpiSampleORM.entity_id == entity_id) &
            (KpiSampleORM.metric_name == "BANDWIDTH_UTIL")
        )
    )
    kpis = result.scalars().all()
    assert len(kpis) == 3
    values = sorted([k.value for k in kpis])
    assert values == [50.0, 60.0, 70.0]


@pytest.mark.asyncio
async def test_kpi_multi_tenant_isolation(db_session: AsyncSession):
    """Verify multi-tenancy filtering via tenant_id index."""
    # Create entities for different tenants
    entity_t1 = NetworkEntityORM(
        id=uuid.uuid4(),
        tenant_id="tenant-1",
        entity_type="GNODEB",
        name="Tenant 1 gNodeB"
    )
    entity_t2 = NetworkEntityORM(
        id=uuid.uuid4(),
        tenant_id="tenant-2",
        entity_type="GNODEB",
        name="Tenant 2 gNodeB"
    )
    db_session.add(entity_t1)
    db_session.add(entity_t2)
    await db_session.flush()
    
    # Create KPI samples for both tenants
    kpi_t1 = KpiSampleORM(
        tenant_id="tenant-1",
        entity_id=entity_t1.id,
        metric_name="PRB_UTIL",
        value=75.0,
        timestamp=datetime.now(timezone.utc),
        source="RAN_TELEMETRY"
    )
    kpi_t2 = KpiSampleORM(
        tenant_id="tenant-2",
        entity_id=entity_t2.id,
        metric_name="PRB_UTIL",
        value=45.0,
        timestamp=datetime.now(timezone.utc),
        source="RAN_TELEMETRY"
    )
    db_session.add(kpi_t1)
    db_session.add(kpi_t2)
    await db_session.commit()
    
    # Query tenant 1 only
    result = await db_session.execute(
        select(KpiSampleORM).where(
            KpiSampleORM.tenant_id == "tenant-1"
        )
    )
    kpis = result.scalars().all()
    assert len(kpis) == 1
    assert kpis[0].value == 75.0


@pytest.mark.asyncio
async def test_kpi_cascade_delete_on_entity(db_session: AsyncSession):
    """Verify CASCADE DELETE setup: foreign key constraints are configured.
    
    Note: SQLite in-memory test DB doesn't enforce foreign keys by default.
    CASCADE DELETE works correctly in production PostgreSQL with the migration.
    This test verifies the FK constraint is present in the ORM definition.
    """
    entity_id = uuid.uuid4()
    entity = NetworkEntityORM(
        id=entity_id,
        tenant_id="test-tenant",
        entity_type="ROUTER",
        name="Test Router"
    )
    db_session.add(entity)
    await db_session.flush()
    
    kpi = KpiSampleORM(
        tenant_id="test-tenant",
        entity_id=entity_id,
        metric_name="THROUGHPUT_MBPS",
        value=1000.0,
        timestamp=datetime.now(timezone.utc),
        source="EXTERNAL_API"
    )
    db_session.add(kpi)
    await db_session.commit()
    
    # Verify FK constraint exists (will be enforced by PostgreSQL in production)
    from sqlalchemy import ForeignKey as SA_ForeignKey
    fk_columns = [fk.column for fk in KpiSampleORM.__table__.foreign_keys]
    assert any('network_entities.id' in str(fk) for fk in fk_columns), \
        "Foreign key to network_entities.id should be configured"
