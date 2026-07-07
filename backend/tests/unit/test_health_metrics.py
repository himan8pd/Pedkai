"""Unit tests for the abeyance memory health-metrics endpoint (PRF-03).

Calls the route function directly against an aiosqlite session. Postgres-only
column types (JSONB, UUID, pgvector Vector) are compiled to sqlite-friendly
equivalents via @compiles shims so the abeyance tables can be created in sqlite.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from pgvector.sqlalchemy import Vector

from backend.app.api import abeyance as abeyance_api
from backend.app.api.abeyance import health_metrics
from backend.app.core.security import INCIDENT_READ, User
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentHistoryORM,
    SnapDecisionRecordORM,
)


# --- sqlite compilation shims for Postgres-only types -----------------------
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "TEXT"


TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"


def _fake_user(tenant_id: str | None = TENANT) -> User:
    return User(
        username="tester",
        user_id=str(uuid.uuid4()),
        role="admin",
        scopes=[INCIDENT_READ],
        tenant_id=tenant_id,
    )


async def _make_session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for orm in (AbeyanceFragmentORM, FragmentHistoryORM, SnapDecisionRecordORM):
            await conn.run_sync(orm.__table__.create)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class _FakeDiscoveryLoop:
    def __init__(self, counts):
        self._counts = counts

    def get_error_counts(self):
        return dict(self._counts)


@pytest.fixture(autouse=True)
def _mock_services(monkeypatch):
    """Mock _get_services so discovery_loop.get_error_counts() is deterministic."""
    error_counts = {"bridge_detector": 3, "surprise_engine": 1}
    monkeypatch.setattr(
        abeyance_api,
        "_get_services",
        lambda: {"discovery_loop": _FakeDiscoveryLoop(error_counts)},
    )
    return error_counts


@pytest.mark.asyncio
async def test_empty_tenant_returns_zeros_and_nulls(_mock_services):
    """An empty tenant returns valid JSON with zeros/nulls, no exceptions."""
    session_maker = await _make_session_maker()
    async with session_maker() as db:
        result = await health_metrics(
            tenant_id=None, db=db, current_user=_fake_user()
        )

    assert result["tenant_id"] == TENANT
    assert result["fragments_by_status"] == {}
    assert result["last_decay_pass_at"] is None
    assert result["hours_since_decay"] is None
    assert result["snaps_24h"] == 0
    assert result["near_misses_24h"] == 0
    # discovery_errors comes from the mocked discovery loop.
    assert result["discovery_errors"] == {"bridge_detector": 3, "surprise_engine": 1}


@pytest.mark.asyncio
async def test_populated_tenant_metrics(_mock_services):
    """Counts, decay age, and 24h snap/near-miss counts are computed correctly."""
    now = datetime.now(timezone.utc)
    session_maker = await _make_session_maker()

    async with session_maker() as db:
        # Fragments by status for TENANT.
        for status in ("ACTIVE", "ACTIVE", "SNAPPED"):
            db.add(AbeyanceFragmentORM(tenant_id=TENANT, source_type="alarm", snap_status=status))
        # A fragment for another tenant that must NOT be counted.
        db.add(AbeyanceFragmentORM(tenant_id=OTHER_TENANT, source_type="alarm", snap_status="ACTIVE"))

        # Decay history: newest DECAY_UPDATE is 5 hours ago.
        frag_id = uuid.uuid4()
        db.add(FragmentHistoryORM(
            fragment_id=frag_id, tenant_id=TENANT, event_type="DECAY_UPDATE",
            event_timestamp=now - timedelta(hours=10),
        ))
        db.add(FragmentHistoryORM(
            fragment_id=frag_id, tenant_id=TENANT, event_type="DECAY_UPDATE",
            event_timestamp=now - timedelta(hours=5),
        ))
        # A non-decay event and another tenant's decay must be ignored.
        db.add(FragmentHistoryORM(
            fragment_id=frag_id, tenant_id=TENANT, event_type="CREATED",
            event_timestamp=now - timedelta(hours=1),
        ))
        db.add(FragmentHistoryORM(
            fragment_id=uuid.uuid4(), tenant_id=OTHER_TENANT, event_type="DECAY_UPDATE",
            event_timestamp=now - timedelta(hours=1),
        ))

        # Snap decisions: within 24h -> counted; older -> ignored; other tenant -> ignored.
        def _sdr(tenant, decision, hours_ago):
            return SnapDecisionRecordORM(
                tenant_id=tenant,
                new_fragment_id=uuid.uuid4(),
                candidate_fragment_id=uuid.uuid4(),
                evaluated_at=now - timedelta(hours=hours_ago),
                failure_mode_profile="DARK_NODE",
                score_entity_overlap=1.0,
                masks_active={},
                weights_used={},
                raw_composite=0.5,
                temporal_modifier=1.0,
                final_score=0.8,
                threshold_applied=0.7,
                decision=decision,
            )

        db.add(_sdr(TENANT, "SNAP", 2))
        db.add(_sdr(TENANT, "SNAP", 20))
        db.add(_sdr(TENANT, "NEAR_MISS", 3))
        db.add(_sdr(TENANT, "SNAP", 30))       # older than 24h -> excluded
        db.add(_sdr(OTHER_TENANT, "SNAP", 1))  # other tenant -> excluded
        await db.commit()

        result = await health_metrics(
            tenant_id=None, db=db, current_user=_fake_user()
        )

    assert result["fragments_by_status"] == {"ACTIVE": 2, "SNAPPED": 1}
    assert result["last_decay_pass_at"] is not None
    # Newest decay was 5h ago (10h one ignored, other-tenant/non-decay ignored).
    assert 4.9 < result["hours_since_decay"] < 5.1
    assert result["snaps_24h"] == 2       # two SNAP within 24h
    assert result["near_misses_24h"] == 1
    assert result["discovery_errors"] == {"bridge_detector": 3, "surprise_engine": 1}


@pytest.mark.asyncio
async def test_tenant_scoping_uses_query_param_when_user_has_none(_mock_services):
    """When the user carries no tenant, the query param resolves the tenant."""
    session_maker = await _make_session_maker()
    async with session_maker() as db:
        db.add(AbeyanceFragmentORM(tenant_id=OTHER_TENANT, source_type="log", snap_status="ACTIVE"))
        await db.commit()

        result = await health_metrics(
            tenant_id=OTHER_TENANT, db=db, current_user=_fake_user(tenant_id=None)
        )

    assert result["tenant_id"] == OTHER_TENANT
    assert result["fragments_by_status"] == {"ACTIVE": 1}
