"""
Regression tests for the reconciliation build-then-atomic-swap write path.

Guarantee under test: a reconciliation run never leaves the divergence dataset
blank. Detectors write into `reconciliation_results_staging`; the live
`reconciliation_results` table is only replaced by an atomic swap at the very
end of `run()`. So a slow or failed run leaves the previous results intact.

These tests drive the REAL engine methods (`_prepare_staging`, `_bulk_insert`)
against an in-memory SQLite DB with a minimal shared schema (the production
`_ensure_tables` uses Postgres-only DDL), plus the exact swap SQL from `run()`.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from backend.app.services.reconciliation_engine import ReconciliationEngine

# Columns shared by the live + staging tables and the swap INSERT..SELECT.
_COLS = (
    "result_id, tenant_id, run_id, divergence_type, entity_or_relationship, "
    "target_id, target_type, domain, description, attribute_name, "
    "cmdb_value, observed_value, confidence, extra, created_at"
)

_CREATE = """
CREATE TABLE {name} (
    result_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    divergence_type TEXT,
    entity_or_relationship TEXT,
    target_id TEXT,
    target_type TEXT,
    domain TEXT,
    description TEXT,
    attribute_name TEXT,
    cmdb_value TEXT,
    observed_value TEXT,
    confidence REAL DEFAULT 1.0,
    extra TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

# The staging→live copy exactly as performed by the swap at the end of run().
_SWAP_INSERT = f"""
INSERT INTO reconciliation_results ({_COLS})
SELECT {_COLS} FROM reconciliation_results_staging WHERE tenant_id = :tid
"""


def _record(result_id: str, run_id: str, tenant: str = "t1") -> dict:
    return {
        "result_id": result_id,
        "tenant_id": tenant,
        "run_id": run_id,
        "divergence_type": "phantom_node",
        "entity_or_relationship": "entity",
        "target_id": f"tgt-{result_id}",
        "target_type": "CELL",
        "domain": "ran",
        "description": "test",
        "attribute_name": None,
        "cmdb_value": None,
        "observed_value": None,
        "confidence": 0.7,
        "extra": {"peer_coverage": 0.1},
    }


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await s.execute(text(_CREATE.format(name="reconciliation_results")))
        await s.execute(text(_CREATE.format(name="reconciliation_results_staging")))
        await s.commit()
        yield s
    await engine.dispose()


async def _live_ids(s: AsyncSession, tenant="t1") -> set[str]:
    rows = await s.execute(
        text("SELECT result_id FROM reconciliation_results WHERE tenant_id = :t"),
        {"t": tenant},
    )
    return {r[0] for r in rows.fetchall()}


async def _staging_ids(s: AsyncSession, tenant="t1") -> set[str]:
    rows = await s.execute(
        text("SELECT result_id FROM reconciliation_results_staging WHERE tenant_id = :t"),
        {"t": tenant},
    )
    return {r[0] for r in rows.fetchall()}


@pytest.mark.asyncio
async def test_bulk_insert_writes_to_staging_not_live(session):
    """Detectors' _bulk_insert must target staging; live is never touched."""
    eng = ReconciliationEngine(session, session)
    eng.tenant_id, eng.run_id = "t1", "run-new"

    # Pre-existing live data from a previous completed run.
    await session.execute(
        text(
            "INSERT INTO reconciliation_results "
            "(result_id, tenant_id, run_id, divergence_type, confidence) "
            "VALUES ('old-1', 't1', 'run-old', 'dark_node', 0.9)"
        )
    )
    await session.commit()

    await eng._prepare_staging("t1")            # clears staging only
    await eng._bulk_insert([_record("new-1", "run-new")])

    # KEY: live is untouched by detection; staging holds the new row.
    assert await _live_ids(session) == {"old-1"}
    assert await _staging_ids(session) == {"new-1"}


@pytest.mark.asyncio
async def test_prepare_staging_does_not_touch_live(session):
    """_prepare_staging clears staging without blanking live results."""
    eng = ReconciliationEngine(session, session)
    await session.execute(
        text(
            "INSERT INTO reconciliation_results "
            "(result_id, tenant_id, run_id, confidence) VALUES ('old-1','t1','r0',0.5)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO reconciliation_results_staging "
            "(result_id, tenant_id, run_id, confidence) VALUES ('stale','t1','rX',0.5)"
        )
    )
    await session.commit()

    await eng._prepare_staging("t1")
    assert await _live_ids(session) == {"old-1"}      # live intact
    assert await _staging_ids(session) == set()       # staging cleared


@pytest.mark.asyncio
async def test_atomic_swap_replaces_live_with_staging(session):
    """After a successful build, the swap replaces live with the new run."""
    eng = ReconciliationEngine(session, session)
    eng.tenant_id, eng.run_id = "t1", "run-new"

    await session.execute(
        text(
            "INSERT INTO reconciliation_results "
            "(result_id, tenant_id, run_id, confidence) VALUES ('old-1','t1','run-old',0.9)"
        )
    )
    await session.commit()
    await eng._prepare_staging("t1")
    await eng._bulk_insert([_record("new-1", "run-new"), _record("new-2", "run-new")])

    # Perform the swap exactly as run() does.
    await session.execute(text("DELETE FROM reconciliation_results WHERE tenant_id = :tid"), {"tid": "t1"})
    await session.execute(text(_SWAP_INSERT), {"tid": "t1"})
    await session.commit()

    assert await _live_ids(session) == {"new-1", "new-2"}  # swapped in
    assert "old-1" not in await _live_ids(session)          # old gone


@pytest.mark.asyncio
async def test_failed_run_leaves_live_intact(session):
    """If a run dies after partial staging writes (no swap), live is preserved."""
    eng = ReconciliationEngine(session, session)
    eng.tenant_id, eng.run_id = "t1", "run-new"

    await session.execute(
        text(
            "INSERT INTO reconciliation_results "
            "(result_id, tenant_id, run_id, confidence) VALUES ('keep-me','t1','run-old',0.9)"
        )
    )
    await session.commit()
    await eng._prepare_staging("t1")
    await eng._bulk_insert([_record("partial-1", "run-new")])   # detector ran...
    # ...then the run "fails" before the swap — no swap executed.

    # The previous dataset is fully intact — never blank.
    assert await _live_ids(session) == {"keep-me"}
