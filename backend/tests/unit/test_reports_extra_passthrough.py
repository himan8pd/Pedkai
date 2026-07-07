"""Unit tests for UX-01a: pass `rr.extra` through the divergence results API.

The `/divergence/records` list endpoint SELECTs many reconciliation-result
columns but historically NOT `rr.extra`, so PRV-03's `peer_coverage` /
`low_data_confidence` annotations never reached the UI. These tests assert the
column is now selected and JSON-decoded into a dict in the response items,
including when it is NULL.

The route function is called directly with a minimal in-memory aiosqlite
session seeded via raw SQL, so no Postgres / JWT infrastructure is required.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.api.reports import get_divergence_records
from backend.app.core.security import User

TENANT = "tenant-test"


async def _make_session() -> AsyncSession:
    """In-memory aiosqlite session with the minimal schema the query touches."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session = async_sessionmaker(engine, expire_on_commit=False)()

    # Minimal reconciliation_results table — only columns the SELECT references.
    await session.execute(
        text(
            """
            CREATE TABLE reconciliation_results (
                result_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                divergence_type TEXT,
                entity_or_relationship TEXT,
                target_id TEXT,
                target_type TEXT,
                domain TEXT,
                description TEXT,
                attribute_name TEXT,
                cmdb_value TEXT,
                observed_value TEXT,
                confidence REAL,
                created_at TEXT,
                extra TEXT
            )
            """
        )
    )
    # network_entities is LEFT JOINed for name resolution — empty is fine.
    await session.execute(
        text(
            """
            CREATE TABLE network_entities (
                id TEXT,
                tenant_id TEXT,
                name TEXT,
                external_id TEXT
            )
            """
        )
    )
    await session.commit()
    return session


def _user() -> User:
    return User(username="tester", role="admin", tenant_id=TENANT, scopes=["topology:read"])


async def _seed(session: AsyncSession, result_id: str, extra):
    await session.execute(
        text(
            """
            INSERT INTO reconciliation_results
                (result_id, tenant_id, divergence_type, entity_or_relationship,
                 target_id, target_type, domain, description, attribute_name,
                 cmdb_value, observed_value, confidence, created_at, extra)
            VALUES
                (:rid, :tid, 'dark_node', 'entity', 'node-1', 'NR_CELL',
                 'mobile_ran', 'a dark node', NULL, NULL, NULL, 0.9,
                 '2026-07-06T00:00:00+00:00', :extra)
            """
        ),
        {"rid": result_id, "tid": TENANT, "extra": extra},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_records_include_parsed_extra_dict():
    """A JSON-string `extra` is parsed into a dict in the response item."""
    session = await _make_session()
    try:
        await _seed(session, "r1", '{"peer_coverage": 0.1}')

        result = await get_divergence_records(db=session, current_user=_user())

        assert result["total"] == 1
        item = result["records"][0]
        assert item["extra"] == {"peer_coverage": 0.1}
        # Existing fields are unchanged / still present.
        assert item["result_id"] == "r1"
        assert item["divergence_type"] == "dark_node"
        assert item["target_id"] == "node-1"
        assert item["confidence"] == 0.9
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_records_extra_null_is_none():
    """When `extra` is NULL the response item carries None (no crash)."""
    session = await _make_session()
    try:
        await _seed(session, "r2", None)

        result = await get_divergence_records(db=session, current_user=_user())

        item = result["records"][0]
        assert item["extra"] is None
    finally:
        await session.close()
