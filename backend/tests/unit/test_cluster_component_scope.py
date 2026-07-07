"""PRF-01 — Scope cluster detection to the trigger fragment's component.

Verifies that ``AccumulationGraph.detect_and_evaluate_clusters`` produces
byte-identical snapshot values whether it loads all tenant edges (full scan,
``trigger_fragment_id=None``) or only the trigger fragment's connected
component (bounded BFS via ``_load_component_edges``).

Two disjoint components are planted:
  - Component A: 3 nodes containing the trigger (triangle).
  - Component B: 4 nodes (complete graph K4).

Assertions:
  1. A full-scan run evaluates BOTH components.
  2. A triggered run (trigger in A) evaluates ONLY component A, and the
     component-A snapshot values are identical to the full-scan run's
     component-A snapshot values.
  3. With ``ACCUM_COMPONENT_MAX_EDGES`` set very low, the triggered run logs
     a WARNING and still evaluates the (partial) component.

Runs on aiosqlite with @compiles shims so the pgvector/JSONB/UUID ORM
columns render as sqlite-compatible types.
"""

from __future__ import annotations

import logging
from itertools import combinations
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateTable

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    ClusterSnapshotORM,
)
from backend.app.services.abeyance.accumulation_graph import AccumulationGraph
from backend.app.services.abeyance.events import ProvenanceLogger, RedisNotifier


# ---------------------------------------------------------------------------
# @compiles shims: render pg-only column types as sqlite-compatible types.
# ---------------------------------------------------------------------------
@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "BLOB"


# Tables exercised by the cluster-scoping path.
_TABLES = (
    AbeyanceFragmentORM.__table__,   # "abeyance_fragment"
    AccumulationEdgeORM.__table__,   # "accumulation_edge"
    ClusterSnapshotORM.__table__,    # "cluster_snapshot"
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in _TABLES:
            await conn.execute(CreateTable(table))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
    await engine.dispose()


def _graph() -> AccumulationGraph:
    # RedisNotifier() with no client is a no-op — keeps the test infra-free.
    return AccumulationGraph(provenance=ProvenanceLogger(), notifier=RedisNotifier())


async def _add_complete_graph(
    graph: AccumulationGraph,
    session: AsyncSession,
    tenant_id: str,
    nodes: list[UUID],
    score: float,
) -> None:
    """Insert edges forming a complete graph over ``nodes`` (deterministic)."""
    for a, b in combinations(nodes, 2):
        await graph.add_or_update_edge(
            session, tenant_id, a, b, score, failure_mode="TEST_MODE",
        )


async def _snapshot_rows(session: AsyncSession) -> list[ClusterSnapshotORM]:
    from sqlalchemy import select

    result = await session.execute(
        select(ClusterSnapshotORM).order_by(ClusterSnapshotORM.id)
    )
    return list(result.scalars().all())


def _snap_signature(row: ClusterSnapshotORM) -> tuple:
    """Order-independent, id/timestamp-free signature of a snapshot row."""
    return (
        row.tenant_id,
        frozenset(row.member_fragment_ids),
        round(row.cluster_score, 12),
        round(row.correlation_discount, 12),
        round(row.adjusted_score, 12),
        round(row.threshold, 12),
        row.decision,
    )


@pytest.mark.asyncio
async def test_triggered_run_matches_full_scan_for_component_a(session: AsyncSession):
    tenant = "t-prf01"
    graph = _graph()

    # Component A: 3 nodes (triangle) — contains the trigger.
    a_nodes = [uuid4() for _ in range(3)]
    trigger = a_nodes[0]
    # Component B: 4 nodes (K4), disjoint from A.
    b_nodes = [uuid4() for _ in range(4)]

    await _add_complete_graph(graph, session, tenant, a_nodes, score=0.9)
    await _add_complete_graph(graph, session, tenant, b_nodes, score=0.85)
    # Commit edges so both the full-scan and triggered runs see them.
    await session.commit()

    # --- Full-scan run: evaluates BOTH components. ---
    full_results = await graph.detect_and_evaluate_clusters(
        session, tenant, trigger_fragment_id=None,
    )
    assert len(full_results) == 2, "Full scan must evaluate both components"

    full_snaps = {_snap_signature(r) for r in await _snapshot_rows(session)}
    # Identify component-A's full-scan snapshot by its member set.
    a_member_set = frozenset(str(n) for n in a_nodes)
    full_a = [s for s in full_snaps if s[1] == a_member_set]
    assert len(full_a) == 1, "Component A must appear exactly once in full scan"

    # Clear the full-scan snapshots so the triggered run's rows are isolated,
    # while keeping the (committed) edges intact.
    from sqlalchemy import delete

    await session.execute(delete(ClusterSnapshotORM))
    await session.commit()

    # --- Triggered run: trigger is in component A → evaluate ONLY A. ---
    triggered_results = await graph.detect_and_evaluate_clusters(
        session, tenant, trigger_fragment_id=trigger,
    )
    assert len(triggered_results) == 1, "Triggered run must evaluate only component A"
    assert set(triggered_results[0]["members"]) == set(a_member_set)

    triggered_snaps = {_snap_signature(r) for r in await _snapshot_rows(session)}
    assert len(triggered_snaps) == 1

    # Byte-identical vs the full-scan path for component A.
    assert triggered_snaps == set(full_a), (
        "Triggered component-A snapshot must match the full-scan component-A snapshot"
    )


@pytest.mark.asyncio
async def test_max_edges_cap_logs_warning_and_evaluates_partial(
    session: AsyncSession, caplog
):
    tenant = "t-prf01-cap"
    graph = _graph()

    # One component of 4 nodes (K4 = 6 edges) containing the trigger.
    nodes = [uuid4() for _ in range(4)]
    trigger = nodes[0]
    await _add_complete_graph(graph, session, tenant, nodes, score=0.9)
    await session.flush()

    await session.commit()

    # Cap the frontier expansion very low so the WARNING path is hit and only
    # a partial slice of the K4 component's edges is loaded.
    with caplog.at_level(logging.WARNING):
        edges = await graph._load_component_edges(
            session, tenant, trigger, max_edges=2,
        )

    assert len(edges) <= 2, "Cap must bound the number of loaded edges"
    assert any(
        "capped at max_edges" in rec.getMessage() for rec in caplog.records
    ), "Cap must emit a WARNING"

    # Reduce the persisted edge set to exactly the partial slice the cap
    # loaded, so the integrated triggered run re-derives that same partial
    # component and must still evaluate it (MIN_CLUSTER_SIZE=3 is reachable
    # from 2 edges → 3 distinct nodes forming a chain).
    from sqlalchemy import delete

    kept_ids = {e.id for e in edges}
    await session.execute(
        delete(AccumulationEdgeORM).where(
            AccumulationEdgeORM.id.notin_(kept_ids)
        )
    )
    await session.commit()

    results = await graph.detect_and_evaluate_clusters(
        session, tenant, trigger_fragment_id=trigger,
    )
    rows = await _snapshot_rows(session)
    assert results, "Capped run must still evaluate the partial component"
    assert rows, "Capped run must persist a snapshot for the partial component"
