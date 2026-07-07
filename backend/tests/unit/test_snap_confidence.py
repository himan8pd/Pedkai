"""
Unit tests for the snap confidence bin-calibration service (PRV-02).

Verifies the ≥N votes rule ported from decision-memory calibration:

* a well-populated final-score decile (>= MIN_VOTES verdicts) returns the
  empirical true-positive rate with ``calibrated=True``;
* a sparse decile falls back to the raw ``final_score`` with
  ``calibrated=False``.

The service is exercised directly (the endpoint is a thin wrapper). An
aiosqlite engine backs the test, with @compiles shims so the Postgres-typed
ORM columns (UUID / JSONB / Vector) map onto sqlite.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# --- sqlite type shims for Postgres-specific column types --------------------
# Must be registered before create_all() compiles the DDL.


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


try:  # pgvector may or may not be importable in the unit env
    from pgvector.sqlalchemy import Vector

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(element, compiler, **kw):  # noqa: ANN001
        return "BLOB"
except Exception:  # pragma: no cover - vector unused by these two tables
    pass


from backend.app.core.database import Base  # noqa: E402
from backend.app.models.abeyance_orm import SnapDecisionRecordORM  # noqa: E402
from backend.app.models.abeyance_v3_orm import (  # noqa: E402
    SnapOutcomeFeedbackORM,
)
from backend.app.services.abeyance import snap_confidence  # noqa: E402

TENANT = "tenant-prv02"
PROFILE = "SILENT_FAILURE"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                SnapDecisionRecordORM.__table__,
                SnapOutcomeFeedbackORM.__table__,
            ],
        )
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _make_decision(final_score: float) -> SnapDecisionRecordORM:
    return SnapDecisionRecordORM(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        new_fragment_id=uuid.uuid4(),
        candidate_fragment_id=uuid.uuid4(),
        evaluated_at=datetime.now(timezone.utc),
        failure_mode_profile=PROFILE,
        score_entity_overlap=0.0,
        masks_active={},
        weights_used={},
        raw_composite=final_score,
        temporal_modifier=1.0,
        final_score=final_score,
        threshold_applied=0.5,
        decision="SNAP",
        multiple_comparisons_k=1,
    )


def _make_feedback(record_id, verdict: str) -> SnapOutcomeFeedbackORM:
    return SnapOutcomeFeedbackORM(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        snap_decision_record_id=record_id,
        operator_verdict=verdict,
        resolved_at=datetime.now(timezone.utc),
    )


async def _seed_bin(session, final_score, total, tp_count):
    """Seed `total` decisions in the given score bin, `tp_count` of them TP."""
    for i in range(total):
        rec = _make_decision(final_score)
        session.add(rec)
        verdict = "TRUE_POSITIVE" if i < tp_count else "FALSE_POSITIVE"
        session.add(_make_feedback(rec.id, verdict))
    await session.flush()


@pytest.mark.asyncio
async def test_populated_bin_returns_empirical_rate(session, monkeypatch):
    # MIN_VOTES defaults to 50; seed 60 votes / 45 TP in bin 7 (score 0.75).
    monkeypatch.setattr(snap_confidence, "MIN_VOTES", 50)
    await _seed_bin(session, 0.75, total=60, tp_count=45)

    result = await snap_confidence.get_calibrated_confidence(
        session, TENANT, PROFILE, 0.75
    )

    assert result["calibrated"] is True
    assert result["votes"] == 60
    assert result["bin"] == 7
    assert result["confidence"] == pytest.approx(0.75)  # 45 / 60


@pytest.mark.asyncio
async def test_sparse_bin_falls_back_to_raw_score(session, monkeypatch):
    monkeypatch.setattr(snap_confidence, "MIN_VOTES", 50)
    # Only 5 votes in bin 3 (score 0.35) -> below threshold.
    await _seed_bin(session, 0.35, total=5, tp_count=5)

    result = await snap_confidence.get_calibrated_confidence(
        session, TENANT, PROFILE, 0.35
    )

    assert result["calibrated"] is False
    assert result["votes"] == 5
    assert result["bin"] == 3
    assert result["confidence"] == pytest.approx(0.35)  # raw score


@pytest.mark.asyncio
async def test_bin_isolation_by_profile_and_bin(session, monkeypatch):
    monkeypatch.setattr(snap_confidence, "MIN_VOTES", 50)
    # 60 populated votes live in bin 7; querying bin 2 sees none of them.
    await _seed_bin(session, 0.75, total=60, tp_count=45)

    result = await snap_confidence.get_calibrated_confidence(
        session, TENANT, PROFILE, 0.25
    )

    assert result["votes"] == 0
    assert result["calibrated"] is False
    assert result["confidence"] == pytest.approx(0.25)
    assert result["bin"] == 2

    # Different profile in the same populated bin is also isolated.
    other = await snap_confidence.get_calibrated_confidence(
        session, TENANT, "COLD_START", 0.75
    )
    assert other["votes"] == 0
    assert other["calibrated"] is False


@pytest.mark.asyncio
async def test_score_to_bin_clamps():
    assert snap_confidence._score_to_bin(0.0) == 0
    assert snap_confidence._score_to_bin(1.0) == 9
    assert snap_confidence._score_to_bin(0.99) == 9
    assert snap_confidence._score_to_bin(1.5) == 9
    assert snap_confidence._score_to_bin(-0.2) == 0
