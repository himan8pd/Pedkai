"""Unit tests for WIR-01 — the snap-feedback router.

Exercises ``submit_snap_feedback`` directly against a real in-memory aiosqlite
session so the actual ORM writes (feedback / discovery / value-event rows) are
verified, not mocked. Postgres-only column types (JSONB / UUID / pgvector) are
shimmed to sqlite-friendly SQL via ``@compiles``.

Covers:
  * 404 for an unknown snap decision record,
  * 201 + feedback_id (no ledger id) for a false-positive verdict,
  * 201 + both ids for a CONFIRMED verdict, and confirms the underlying rows
    exist in snap_outcome_feedback, discovery_ledger and value_event.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from pgvector.sqlalchemy import Vector

import backend.app.api.abeyance_feedback as feedback_api
from backend.app.api.abeyance_feedback import SnapFeedbackRequest, submit_snap_feedback
from backend.app.core.database import Base
from backend.app.core.security import User
from backend.app.models.abeyance_orm import (
    DiscoveryLedgerORM,
    SnapDecisionRecordORM,
    ValueEventORM,
)
from backend.app.models.abeyance_v3_orm import SnapOutcomeFeedbackORM


# ---------------------------------------------------------------------------
# sqlite compile shims for Postgres-only column types
# ---------------------------------------------------------------------------

@compiles(JSONB, "sqlite")
def _compile_jsonb(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid(element, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@compiles(Vector, "sqlite")
def _compile_vector(element, compiler, **kw):  # noqa: ANN001
    return "TEXT"


# Only build the four tables this router touches.
_TABLES = [
    SnapDecisionRecordORM.__table__,
    SnapOutcomeFeedbackORM.__table__,
    DiscoveryLedgerORM.__table__,
    ValueEventORM.__table__,
]

TENANT = "tenant-test"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def _real_services():
    """Use the real (dependency-light) service singleton, reset afterwards."""
    feedback_api._services = None
    yield
    feedback_api._services = None


def _user() -> User:
    return User(
        username="tester",
        role="admin",
        tenant_id=TENANT,
        scopes=["incident:read"],
    )


async def _seed_snap_record(session: AsyncSession, tenant: str = TENANT) -> uuid.UUID:
    rec = SnapDecisionRecordORM(
        id=uuid.uuid4(),
        tenant_id=tenant,
        new_fragment_id=uuid.uuid4(),
        candidate_fragment_id=uuid.uuid4(),
        evaluated_at=datetime.now(timezone.utc),
        failure_mode_profile="DARK_EDGE",
        score_semantic=0.5,
        score_topological=0.4,
        score_temporal=0.3,
        score_operational=0.2,
        score_entity_overlap=1.0,
        masks_active={},
        weights_used={},
        raw_composite=0.8,
        temporal_modifier=1.0,
        final_score=0.82,
        threshold_applied=0.7,
        decision="SNAP",
        multiple_comparisons_k=1,
    )
    session.add(rec)
    await session.commit()
    return rec.id


@pytest.mark.asyncio
async def test_unknown_record_returns_404(session):
    from fastapi import HTTPException

    payload = SnapFeedbackRequest(
        snap_decision_record_id=uuid.uuid4(),
        verdict="CONFIRMED",
    )
    with pytest.raises(HTTPException) as exc:
        await submit_snap_feedback(
            payload=payload, tenant_id=None, db=session, current_user=_user()
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_false_positive_records_feedback_only(session):
    rec_id = await _seed_snap_record(session)

    payload = SnapFeedbackRequest(
        snap_decision_record_id=rec_id,
        verdict="FALSE_POSITIVE",
        notes="not related",
    )
    resp = await submit_snap_feedback(
        payload=payload, tenant_id=None, db=session, current_user=_user()
    )

    assert resp["feedback_id"]
    assert resp["value_ledger_id"] is None

    fb = (await session.execute(select(SnapOutcomeFeedbackORM))).scalars().all()
    assert len(fb) == 1
    assert fb[0].operator_verdict == "FALSE_POSITIVE"

    # No ledger / value rows for a false positive.
    assert (await session.execute(select(DiscoveryLedgerORM))).scalars().all() == []
    assert (await session.execute(select(ValueEventORM))).scalars().all() == []


@pytest.mark.asyncio
async def test_confirmed_records_feedback_discovery_and_value(session):
    rec_id = await _seed_snap_record(session)

    payload = SnapFeedbackRequest(
        snap_decision_record_id=rec_id,
        verdict="CONFIRMED",
        resolution_action="restart",
        attributed_hours=2.5,
    )
    resp = await submit_snap_feedback(
        payload=payload, tenant_id=None, db=session, current_user=_user()
    )

    assert resp["feedback_id"]
    assert resp["value_ledger_id"]

    fb = (await session.execute(select(SnapOutcomeFeedbackORM))).scalars().all()
    assert len(fb) == 1
    assert fb[0].operator_verdict == "CONFIRMED"

    ledger = (await session.execute(select(DiscoveryLedgerORM))).scalars().all()
    assert len(ledger) == 1
    assert ledger[0].discovery_type == "SNAP_CONFIRMED"
    assert ledger[0].hypothesis_id == rec_id
    assert ledger[0].discovery_confidence == pytest.approx(0.82)

    events = (await session.execute(select(ValueEventORM))).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "INCIDENT_RESOLUTION"
    assert events[0].attributed_value_hours == pytest.approx(2.5)
    assert events[0].attribution_rationale == "operator confirmed snap"
    assert events[0].ledger_entry_id == ledger[0].id
