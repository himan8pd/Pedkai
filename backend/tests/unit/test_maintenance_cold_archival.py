"""Unit test for WIR-03: cold archival step in maintenance.

Verifies MaintenanceService.archive_expired_fragments:
- Only EXPIRED fragments older than ABEYANCE_COLD_AFTER_DAYS are archived.
- Recent EXPIRED and non-EXPIRED fragments are untouched.
- Archived fragments transition to COLD, get a provenance row, and a
  cold_fragment row is written.

Runs against aiosqlite. PostgreSQL-specific column types (JSONB, UUID,
pgvector Vector) are shimmed via @compiles so the ORM metadata compiles.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# --- Dialect shims: render PG-specific types as portable SQLite types ------
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from pgvector.sqlalchemy import Vector


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(element, compiler, **kw):
    return "TEXT"


from backend.app.core.database import Base
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentHistoryORM,
)
from backend.app.services.abeyance.cold_storage import ColdFragmentORM
from backend.app.services.abeyance.events import ProvenanceLogger
from backend.app.services.abeyance.maintenance import MaintenanceService


TENANT = "tenant-cold-test"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    # Create only the tables this test touches.
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[
                    AbeyanceFragmentORM.__table__,
                    FragmentHistoryORM.__table__,
                    ColdFragmentORM.__table__,
                ],
            )
        )

    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s

    await engine.dispose()


def _make_fragment(status: str, updated_at: datetime) -> AbeyanceFragmentORM:
    return AbeyanceFragmentORM(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        source_type="alarm",
        raw_content="content",
        extracted_entities=[],
        failure_mode_tags=[],
        snap_status=status,
        current_decay_score=0.1,
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_archive_expired_fragments(session):
    os.environ["ABEYANCE_COLD_AFTER_DAYS"] = "30"

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    recent = now - timedelta(days=5)

    expired_old_1 = _make_fragment("EXPIRED", old)
    expired_old_2 = _make_fragment("EXPIRED", old)
    expired_recent = _make_fragment("EXPIRED", recent)
    active = _make_fragment("ACTIVE", old)

    session.add_all([expired_old_1, expired_old_2, expired_recent, active])
    await session.flush()

    svc = MaintenanceService(
        decay_engine=None,
        accumulation_graph=None,
        provenance=ProvenanceLogger(),
    )

    archived = await svc.archive_expired_fragments(session, TENANT)

    # Exactly the two old EXPIRED fragments were archived.
    assert archived == 2

    # Their status transitioned to COLD.
    cold_ids = {expired_old_1.id, expired_old_2.id}
    for frag in (expired_old_1, expired_old_2):
        assert frag.snap_status == "COLD"

    # Untouched fragments retain their status.
    assert expired_recent.snap_status == "EXPIRED"
    assert active.snap_status == "ACTIVE"

    # Two provenance rows recording the archival.
    prov_rows = (
        await session.execute(
            select(FragmentHistoryORM).where(
                FragmentHistoryORM.event_type == "ARCHIVED_COLD"
            )
        )
    ).scalars().all()
    assert len(prov_rows) == 2
    assert {r.fragment_id for r in prov_rows} == cold_ids

    # Two cold_fragment rows exist for the archived originals.
    cold_rows = (
        await session.execute(select(ColdFragmentORM))
    ).scalars().all()
    assert len(cold_rows) == 2
    assert {r.original_fragment_id for r in cold_rows} == cold_ids
