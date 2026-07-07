"""RET-06 — Cold storage must archive v3 semantic embeddings.

Regression coverage: ``archive_to_db`` used to copy the legacy
``enriched_embedding`` column verbatim.  v3 fragments write that legacy
column as NULL and carry the real vector in ``emb_semantic`` (guarded by
``mask_semantic``), so cold search could never match a v3-era fragment.

These tests archive fake fragments through the real ORM path and read the
persisted ``ColdFragmentORM`` row back to assert which vector landed in
``enriched_embedding``:
- a v3 fragment (``mask_semantic=True``, ``emb_semantic`` set) stores the
  semantic vector;
- a legacy fragment (mask false, only ``enriched_embedding`` set) stores the
  legacy vector.

sqlite has no pgvector / JSONB / native UUID, so we register ``@compiles``
DDL shims that emit portable column types, and create ONLY the
``cold_fragment`` table.
"""

from __future__ import annotations

import types
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.app.services.abeyance.cold_storage import (
    AbeyanceColdStorage,
    ColdFragmentORM,
)

try:
    from pgvector.sqlalchemy import Vector
    _HAS_VECTOR = True
except ImportError:  # pragma: no cover - pgvector always present in venv
    Vector = None
    _HAS_VECTOR = False


# ---------------------------------------------------------------------------
# sqlite DDL shims: pgvector / JSONB / PG_UUID have no sqlite representation.
# Emit portable text-ish types so `create_all` for cold_fragment succeeds.
# ---------------------------------------------------------------------------

@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


if _HAS_VECTOR:

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "TEXT"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """In-memory aiosqlite session with only the cold_fragment table."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: ColdFragmentORM.__table__.create(c, checkfirst=True)
        )
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
    await engine.dispose()


def _fake_fragment(**overrides):
    """Fake fragment object matching the attributes archive_to_db reads."""
    base = dict(
        id=uuid.uuid4(),
        source_type="alarm",
        raw_content="raw content here",
        extracted_entities=["ne-1"],
        failure_mode_tags=["timeout"],
        enriched_embedding=None,
        emb_semantic=None,
        mask_semantic=False,
        event_timestamp=None,
        created_at=None,
        current_decay_score=0.5,
        snap_status="EXPIRED",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


async def _fetch_row(session: AsyncSession, cold_id) -> ColdFragmentORM:
    result = await session.execute(
        select(ColdFragmentORM).where(ColdFragmentORM.id == cold_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_v3_fragment_stores_semantic_embedding(session: AsyncSession):
    """mask_semantic=True + emb_semantic set → semantic vector persisted."""
    storage = AbeyanceColdStorage()
    semantic = [0.25] * 1536
    frag = _fake_fragment(
        mask_semantic=True,
        emb_semantic=semantic,
        enriched_embedding=None,  # v3 writes legacy column NULL
    )

    cold = await storage.archive_to_db(session, frag, tenant_id="tenant-a")

    row = await _fetch_row(session, cold.id)
    assert row.enriched_embedding is not None
    assert list(row.enriched_embedding) == semantic


@pytest.mark.asyncio
async def test_legacy_fragment_stores_enriched_embedding(session: AsyncSession):
    """mask false + only enriched_embedding set → legacy vector persisted."""
    storage = AbeyanceColdStorage()
    legacy = [0.75] * 1536
    frag = _fake_fragment(
        mask_semantic=False,
        emb_semantic=None,
        enriched_embedding=legacy,
    )

    cold = await storage.archive_to_db(session, frag, tenant_id="tenant-b")

    row = await _fetch_row(session, cold.id)
    assert row.enriched_embedding is not None
    assert list(row.enriched_embedding) == legacy


@pytest.mark.asyncio
async def test_mask_false_ignores_semantic_even_if_present(session: AsyncSession):
    """Guard: mask_semantic=False falls back to legacy even if emb_semantic set."""
    storage = AbeyanceColdStorage()
    legacy = [0.1] * 1536
    semantic = [0.9] * 1536
    frag = _fake_fragment(
        mask_semantic=False,
        emb_semantic=semantic,
        enriched_embedding=legacy,
    )

    cold = await storage.archive_to_db(session, frag, tenant_id="tenant-c")

    row = await _fetch_row(session, cold.id)
    assert list(row.enriched_embedding) == legacy
