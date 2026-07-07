"""
WIR-05b — Value event on incident close.

Verifies that closing an incident through the human close-gate records an
INCIDENT_RESOLUTION value event *only* when an AI recommendation existed for it
(qualified via ``decision_trace_id``), and that a failing value service never
blocks closure.

Self-contained: builds its own in-memory aiosqlite engine with JSONB/UUID/Vector
``@compiles`` shims and creates only the three tables under test
(incidents, incident_audit_entries, value_event). The value_event table is
created with a NULLABLE ledger_entry_id to reflect the WIR-05a migration
(the ORM column default is NOT NULL in this tree, but ledger_entry_id=None is
legal at the DB level after WIR-05a).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector


# --- SQLite compatibility shims (JSONB/Vector/UUID are Postgres-only) ---------
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # pragma: no cover - trivial
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):  # pragma: no cover - trivial
    return "TEXT"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # pragma: no cover - trivial
    return "VARCHAR(36)"


from backend.app.api import incidents as incidents_api
from backend.app.models.incident_orm import IncidentORM
from backend.app.models.audit_orm import IncidentAuditEntryORM
from backend.app.models.abeyance_orm import ValueEventORM
from backend.app.schemas.incidents import IncidentStatus


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _make_engine():
    return create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


async def _create_schema(engine):
    """Create only the three tables under test.

    value_event is created with an explicit NULLABLE ledger_entry_id (WIR-05a),
    since the ORM column is declared NOT NULL in this tree.
    """
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: IncidentORM.__table__.create(sync_conn, checkfirst=True)
        )
        await conn.run_sync(
            lambda sync_conn: IncidentAuditEntryORM.__table__.create(
                sync_conn, checkfirst=True
            )
        )
        # value_event with NULLABLE ledger_entry_id
        await conn.execute(
            text(
                """
                CREATE TABLE value_event (
                    id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    ledger_entry_id VARCHAR(36) NULL,
                    event_type VARCHAR(50) NOT NULL,
                    event_at TIMESTAMP,
                    event_detail JSON NOT NULL DEFAULT '{}',
                    attributed_value_hours FLOAT NULL,
                    attributed_value_currency FLOAT NULL,
                    attribution_rationale TEXT NULL
                )
                """
            )
        )


class _FakeUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id


class _ApprovalPayload:
    def __init__(self, approved_by: str):
        self.approved_by = approved_by


async def _seed_incident(session: AsyncSession, *, tenant_id, decision_trace_id, priority):
    """Insert an incident in RESOLUTION_APPROVED (gate-satisfied for close)."""
    incident = IncidentORM(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        title="test incident",
        severity="critical",
        status=IncidentStatus.RESOLUTION_APPROVED.value,
        priority=priority,
        decision_trace_id=decision_trace_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(incident)
    await session.flush()
    return incident


@pytest.mark.asyncio
async def test_close_qualifying_incident_records_value_event():
    """decision_trace_id set + priority P2 -> one value_event (2.0h, NULL ledger) + audit."""
    engine = _make_engine()
    await _create_schema(engine)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        incident = await _seed_incident(
            session,
            tenant_id="tenantA",
            decision_trace_id=str(uuid.uuid4()),
            priority="P2",
        )

        result = await incidents_api.close_incident(
            incident_id=incident.id,
            payload=_ApprovalPayload("engineer1"),
            db=session,
            current_user=_FakeUser("tenantA"),
        )

        # Incident is CLOSED
        assert incident.status == IncidentStatus.CLOSED.value

        # Exactly one value_event, correct fields
        events = (await session.execute(select(ValueEventORM))).scalars().all()
        assert len(events) == 1
        ev = events[0]
        assert ev.event_type == "INCIDENT_RESOLUTION"
        assert ev.attributed_value_hours == 2.0
        assert ev.attributed_value_currency is None
        assert ev.ledger_entry_id is None
        assert "priority P2 -> 2.0h" in ev.attribution_rationale
        assert ev.event_detail["decision_trace_id"] == incident.decision_trace_id
        assert ev.event_detail["priority"] == "P2"
        assert ev.event_detail["policy"] == "fixed_table_v1"

        # One value_event_recorded audit entry (SYSTEM/system)
        audits = (
            await session.execute(
                select(IncidentAuditEntryORM).where(
                    IncidentAuditEntryORM.action == "value_event_recorded"
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].action_type == "SYSTEM"
        assert audits[0].actor == "system"

    await engine.dispose()


@pytest.mark.asyncio
async def test_close_non_qualifying_incident_records_no_value_event():
    """No decision_trace_id -> neither value_event nor value_event_recorded audit."""
    engine = _make_engine()
    await _create_schema(engine)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        incident = await _seed_incident(
            session,
            tenant_id="tenantB",
            decision_trace_id=None,
            priority="P1",
        )

        await incidents_api.close_incident(
            incident_id=incident.id,
            payload=_ApprovalPayload("engineer2"),
            db=session,
            current_user=_FakeUser("tenantB"),
        )

        assert incident.status == IncidentStatus.CLOSED.value

        events = (await session.execute(select(ValueEventORM))).scalars().all()
        assert len(events) == 0

        audits = (
            await session.execute(
                select(IncidentAuditEntryORM).where(
                    IncidentAuditEntryORM.action == "value_event_recorded"
                )
            )
        ).scalars().all()
        assert len(audits) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_value_service_failure_does_not_block_closure(monkeypatch):
    """A raising value service must not block closure: incident still CLOSED, no crash."""
    engine = _make_engine()
    await _create_schema(engine)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    class _BoomService:
        async def record_value_event(self, *a, **k):
            raise RuntimeError("boom")

    def _fake_factory(*a, **k):
        return {"value_attribution": _BoomService()}

    # The route imports create_abeyance_services from backend.app.services.abeyance
    monkeypatch.setattr(
        "backend.app.services.abeyance.create_abeyance_services", _fake_factory
    )

    async with Session() as session:
        incident = await _seed_incident(
            session,
            tenant_id="tenantC",
            decision_trace_id=str(uuid.uuid4()),
            priority="P3",
        )

        # Should NOT raise despite the value service blowing up
        await incidents_api.close_incident(
            incident_id=incident.id,
            payload=_ApprovalPayload("engineer3"),
            db=session,
            current_user=_FakeUser("tenantC"),
        )

        assert incident.status == IncidentStatus.CLOSED.value

        # No value_event persisted (service raised before insert completed)
        events = (await session.execute(select(ValueEventORM))).scalars().all()
        assert len(events) == 0

    await engine.dispose()
