"""RET-02: neighbourhood entity refs written during enrichment.

Verifies that the 2-hop topology expansion (neighbourhood["depths"]) is
persisted to fragment_entity_ref with topological_distance > 0, bounded by
MAX_NEIGHBOURHOOD_REFS, closest depths first, deduped against extracted ids.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    FragmentHistoryORM,
)
from backend.app.services.abeyance.enrichment_chain_v3 import (
    EnrichmentChainV3,
    MAX_NEIGHBOURHOOD_REFS,
)
from backend.app.services.abeyance.events import ProvenanceLogger


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


class _StubShadowTopology:
    """Returns a fixed neighbourhood depths dict for deterministic testing."""

    def __init__(self, depths: dict):
        self._depths = depths

    async def get_neighbourhood(self, session, tenant_id, entity_ids, max_hops=2):
        return {
            "entities": [],
            "relationships": [],
            "depths": self._depths,
            "total_entities": 0,
            "total_relationships": 0,
        }


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AbeyanceFragmentORM.__table__.create)
        await conn.run_sync(FragmentEntityRefORM.__table__.create)
        await conn.run_sync(FragmentHistoryORM.__table__.create)
    async_session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield async_session
    finally:
        await async_session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_neighbour_refs_written_bounded_and_deduped(session):
    tenant_id = "t1"
    seed = "ENB-1"  # extracted entity, also depth-0 id

    depth1 = [f"N1-{i}" for i in range(50)]
    depth2 = [f"N2-{i}" for i in range(50)]
    depths = {0: [seed], 1: depth1, 2: depth2}

    chain = EnrichmentChainV3(
        provenance=ProvenanceLogger(),
        shadow_topology=_StubShadowTopology(depths),
    )

    # explicit_entity_refs guarantees the seed is extracted deterministically.
    fragment = await chain.enrich(
        session=session,
        tenant_id=tenant_id,
        raw_content="Fault on ENB-1 core segment.",
        source_type="ALARM",
        explicit_entity_refs=[seed],
    )

    result = await session.execute(
        select(FragmentEntityRefORM).where(
            FragmentEntityRefORM.fragment_id == fragment.id
        )
    )
    refs = list(result.scalars().all())

    neighbours = [r for r in refs if r.topological_distance > 0]
    extracted = [r for r in refs if r.topological_distance == 0]

    # Exactly MAX_NEIGHBOURHOOD_REFS (64) neighbour refs written.
    assert MAX_NEIGHBOURHOOD_REFS == 64
    assert len(neighbours) == 64

    # All depth-1 identifiers included (closest depths first).
    depth1_written = {r.entity_identifier for r in neighbours if r.topological_distance == 1}
    assert set(depth1) == depth1_written

    # Remaining budget filled from depth 2 (64 - 50 = 14).
    depth2_written = {r.entity_identifier for r in neighbours if r.topological_distance == 2}
    assert len(depth2_written) == 14
    assert depth2_written <= set(depth2)

    # Extracted seed present exactly once at distance 0, not duplicated as a neighbour.
    assert any(r.entity_identifier == seed for r in extracted)
    assert all(r.entity_identifier != seed for r in neighbours)
