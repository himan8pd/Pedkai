"""RET-05: retrieval regression suite for SnapEngineV3.

Exercises the RET-01 merged retrieval paths (`_targeted_retrieval`,
`_vector_retrieval`) against a real in-memory SQLite engine using the same
Postgres-column shims as the enrichment tests. These tests lock in:

  1. entity-overlap retrieval returns exactly the partner fragment.
  2. a distance-2-only shared ref still surfaces the candidate via the entity
     path, while every persisted score_entity_overlap is 0.0 (scoring uses the
     distance-0 set only).
  3. no shared refs on SQLite ⇒ 0 candidates (vector path degraded to []).
  4. `_vector_retrieval` on SQLite ⇒ [] plus a WARNING.
  5. the postgres-dialect compile of a cosine_distance ordering uses "<=>".
  6. a fragment is never returned as a candidate for itself (self-exclusion).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from pgvector.sqlalchemy import Vector

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    FragmentHistoryORM,
    SnapDecisionRecordORM,
)
from backend.app.services.abeyance.events import ProvenanceLogger, RedisNotifier
from backend.app.services.abeyance.snap_engine_v3 import SnapEngineV3


# --- SQLite dialect shims for Postgres-only column types ---
@compiles(postgresql.JSONB, "sqlite")
def _compile_jsonb(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(postgresql.UUID, "sqlite")
def _compile_uuid(element, compiler, **kw):  # noqa: ANN001
    return "CHAR(32)"


@compiles(Vector, "sqlite")
def _compile_vector(element, compiler, **kw):  # noqa: ANN001
    return "TEXT"


TENANT = "t-ret05"


@pytest_asyncio.fixture
async def session():
    # StaticPool keeps a single shared connection for the in-memory DB so the
    # schema created below survives across the engine's connections.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(AbeyanceFragmentORM.__table__.create)
        await conn.run_sync(FragmentEntityRefORM.__table__.create)
        await conn.run_sync(FragmentHistoryORM.__table__.create)
        await conn.run_sync(SnapDecisionRecordORM.__table__.create)
    async_session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield async_session
    finally:
        await async_session.close()
        await engine.dispose()


def _make_engine() -> SnapEngineV3:
    # Bare RedisNotifier (no client) is a no-op that only logs; ProvenanceLogger
    # writes to the fragment_history table which we create in the fixture.
    return SnapEngineV3(provenance=ProvenanceLogger(), notifier=RedisNotifier())


async def _add_fragment(
    session: AsyncSession,
    *,
    failure_mode: str = "DARK_EDGE",
    snap_status: str = "ACTIVE",
    decay: float = 1.0,
    event_time: datetime | None = None,
) -> AbeyanceFragmentORM:
    """Insert a masks-off fragment.

    All embedding masks are False, so the CHECK constraints
    (ck_frag_mask_*) are satisfied with NULL embeddings, and scoring is
    driven solely by the temporal + entity_overlap dimensions.
    """
    frag = AbeyanceFragmentORM(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        source_type="ALARM",
        raw_content="x",
        extracted_entities=[],
        topological_neighbourhood={},
        operational_fingerprint={},
        failure_mode_tags=[failure_mode],
        temporal_context={},
        mask_semantic=False,
        mask_topological=False,
        mask_operational=False,
        embedding_mask=[True, False, True, False],
        event_timestamp=event_time or datetime(2026, 1, 1, tzinfo=timezone.utc),
        base_relevance=1.0,
        current_decay_score=decay,
        snap_status=snap_status,
    )
    session.add(frag)
    await session.flush()
    return frag


async def _add_ref(
    session: AsyncSession,
    frag: AbeyanceFragmentORM,
    identifier: str,
    distance: int = 0,
) -> None:
    session.add(
        FragmentEntityRefORM(
            id=uuid.uuid4(),
            fragment_id=frag.id,
            entity_identifier=identifier,
            topological_distance=distance,
            tenant_id=TENANT,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# 1. entity-overlap retrieval returns exactly the partner fragment
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_entity_overlap_returns_partner(session):
    engine = _make_engine()

    new_frag = await _add_fragment(session)
    partner = await _add_fragment(session)
    noise = await _add_fragment(session)

    await _add_ref(session, new_frag, "ENB-1", distance=0)
    await _add_ref(session, partner, "ENB-1", distance=0)
    await _add_ref(session, noise, "ENB-99", distance=0)

    candidates = await engine._targeted_retrieval(
        session, TENANT, new_frag, {"ENB-1"},
    )

    ids = {c.id for c in candidates}
    assert ids == {partner.id}


# ---------------------------------------------------------------------------
# 2. distance-2-only shared ref ⇒ retrieved via entity path, overlap == 0.0
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_distance2_shared_ref_retrieved_overlap_zero(session):
    engine = _make_engine()

    new_frag = await _add_fragment(session)
    candidate = await _add_fragment(session)

    # Their ONLY shared identifier ("ENB-FAR") sits at topological_distance=2
    # for the new fragment. Each also has its own distinct distance-0 entity so
    # the distance-0 overlap is empty.
    await _add_ref(session, new_frag, "NEW-SEED", distance=0)
    await _add_ref(session, new_frag, "ENB-FAR", distance=2)
    await _add_ref(session, candidate, "ENB-FAR", distance=0)

    result = await engine.evaluate(session, new_frag, TENANT)

    # The candidate was reachable through the shared distance-2 identifier.
    assert result["candidates_evaluated"] == 1

    sdr_rows = (
        (await session.execute(select(SnapDecisionRecordORM))).scalars().all()
    )
    assert sdr_rows, "expected at least one persisted snap decision record"
    assert all(r.candidate_fragment_id == candidate.id for r in sdr_rows)
    # Scoring uses only the distance-0 set → zero entity overlap on every row.
    assert all(r.score_entity_overlap == 0.0 for r in sdr_rows)


# ---------------------------------------------------------------------------
# 3. no shared refs on SQLite ⇒ 0 candidates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_shared_refs_zero_candidates(session):
    engine = _make_engine()

    new_frag = await _add_fragment(session)
    other = await _add_fragment(session)

    await _add_ref(session, new_frag, "ENB-1", distance=0)
    await _add_ref(session, other, "ENB-2", distance=0)

    candidates = await engine._targeted_retrieval(
        session, TENANT, new_frag, {"ENB-1"},
    )
    assert candidates == []


# ---------------------------------------------------------------------------
# 4. _vector_retrieval on SQLite ⇒ [] plus a WARNING
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_vector_retrieval_degrades_on_sqlite(session, caplog):
    engine = _make_engine()
    new_frag = await _add_fragment(session)

    with caplog.at_level(logging.WARNING):
        result = await engine._vector_retrieval(session, TENANT, new_frag)

    assert result == []
    assert any(
        record.levelno == logging.WARNING
        and "non-postgresql" in record.getMessage().lower()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. postgres-dialect compile of cosine_distance uses "<=>"
# ---------------------------------------------------------------------------
def test_cosine_distance_compiles_to_pg_operator():
    expr = AbeyanceFragmentORM.emb_semantic.cosine_distance([0.0] * 1536)
    compiled = str(
        expr.compile(dialect=postgresql.dialect())
    )
    assert "<=>" in compiled


# ---------------------------------------------------------------------------
# 6. self-exclusion: a fragment never appears in its own candidate list
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_self_exclusion(session):
    engine = _make_engine()

    new_frag = await _add_fragment(session)
    partner = await _add_fragment(session)

    # Both fragments carry the same distance-0 identifier, so the entity query
    # would match new_frag too if self-exclusion were absent.
    await _add_ref(session, new_frag, "ENB-1", distance=0)
    await _add_ref(session, partner, "ENB-1", distance=0)

    candidates = await engine._targeted_retrieval(
        session, TENANT, new_frag, {"ENB-1"},
    )

    ids = {c.id for c in candidates}
    assert new_frag.id not in ids
    assert ids == {partner.id}
