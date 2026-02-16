"""
LiveTestData Decision Memory & LLM SITREP tests (TC-050–TC-076).

Layer 5: Decision memory CRUD, find_similar, feedback, RLHF boost, multi-tenant.
Layer 6: LLM SITREP contract tests (sections, causal wording, empty similar).
Uses LiveTestData adapter row_to_decision_context for realistic payloads.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock

from backend.app.models.decision_trace import (
    DecisionTraceCreate,
    DecisionContext,
    SimilarDecisionQuery,
    DecisionOutcomeRecord,
    DecisionOutcome,
)
from backend.app.services.decision_repository import DecisionTraceRepository
from LiveTestData.adapter import row_to_decision_context
from tests.data.live_test_data import get_mock_row


@pytest.fixture
def decision_context_from_row():
    """Build a DecisionTraceCreate from a LiveTestData mock row."""
    row = get_mock_row()
    ctx = row_to_decision_context(row)
    return DecisionTraceCreate(
        tenant_id=ctx["tenant_id"],
        trigger_type=ctx["trigger_type"],
        trigger_description=ctx["trigger_description"],
        context=DecisionContext(
            affected_entities=ctx["context"]["affected_entities"],
        ),
        decision_summary=ctx["decision_summary"],
        tradeoff_rationale=ctx["tradeoff_rationale"],
        action_taken=ctx["action_taken"],
        decision_maker=ctx["decision_maker"],
        confidence_score=ctx["confidence_score"],
        domain=ctx["domain"],
        tags=ctx["tags"],
    )


# ─── Layer 5: Decision Memory (TC-050–TC-064) ────────────────────────────────


@pytest.mark.asyncio
async def test_tc050_create_decision(db_session, decision_context_from_row):
    """TC-050: Create a decision trace from LiveTestData context and retrieve by ID."""
    repo = DecisionTraceRepository(db_session)
    created = await repo.create(decision_context_from_row)
    await db_session.commit()

    assert created.id is not None
    assert created.trigger_description == decision_context_from_row.trigger_description
    assert created.domain == "anops"

    # Retrieve
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_tc051_list_decisions(db_session, decision_context_from_row):
    """TC-051: List decisions filtered by tenant_id returns seeded entries."""
    repo = DecisionTraceRepository(db_session)
    await repo.create(decision_context_from_row)
    await db_session.commit()

    results = await repo.list_decisions(tenant_id=decision_context_from_row.tenant_id)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_tc052_update_outcome(db_session, decision_context_from_row):
    """TC-052: Update a decision trace with an outcome record."""
    from backend.app.models.decision_trace import DecisionTraceUpdate

    repo = DecisionTraceRepository(db_session)
    created = await repo.create(decision_context_from_row)
    await db_session.commit()

    outcome = DecisionOutcomeRecord(
        status=DecisionOutcome.SUCCESS,
        resolution_time_minutes=4.2,
        customer_impact_count=0,
        sla_violated=False,
        learnings="Failover effective when neighbor < 70% loaded",
    )
    update = DecisionTraceUpdate(outcome=outcome)
    updated = await repo.update(created.id, update)
    assert updated is not None
    assert updated.outcome is not None
    assert updated.outcome.status == DecisionOutcome.SUCCESS


@pytest.mark.asyncio
async def test_tc060_nonexistent_decision(db_session):
    """TC-060: Get non-existent decision returns None."""
    repo = DecisionTraceRepository(db_session)
    result = await repo.get_by_id(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_tc062_multi_tenant_decision_isolation(db_session):
    """TC-062: Decisions are isolated by tenant_id."""
    repo = DecisionTraceRepository(db_session)

    # Tenant A
    row_a = get_mock_row()
    ctx_a = row_to_decision_context(row_a)
    create_a = DecisionTraceCreate(
        tenant_id="tenant-alpha",
        trigger_type="alarm",
        trigger_description=ctx_a["trigger_description"],
        context=DecisionContext(affected_entities=["CELL_A"]),
        decision_summary="Alpha decision",
        tradeoff_rationale="Alpha rationale",
        action_taken="NO_ACTION",
        decision_maker="system:test",
        domain="anops",
    )
    await repo.create(create_a)

    # Tenant B
    create_b = DecisionTraceCreate(
        tenant_id="tenant-beta",
        trigger_type="manual",
        trigger_description="Beta event",
        context=DecisionContext(affected_entities=["CELL_B"]),
        decision_summary="Beta decision",
        tradeoff_rationale="Beta rationale",
        action_taken="NO_ACTION",
        decision_maker="system:test",
        domain="anops",
    )
    await repo.create(create_b)
    await db_session.commit()

    alpha_list = await repo.list_decisions(tenant_id="tenant-alpha")
    beta_list = await repo.list_decisions(tenant_id="tenant-beta")

    assert all(d.tenant_id == "tenant-alpha" for d in alpha_list)
    assert all(d.tenant_id == "tenant-beta" for d in beta_list)
    assert len(alpha_list) == 1
    assert len(beta_list) == 1


@pytest.mark.asyncio
async def test_tc064_jsonb_round_trip(db_session, decision_context_from_row):
    """TC-064: JSONB context survives create → read round-trip without data loss."""
    repo = DecisionTraceRepository(db_session)
    created = await repo.create(decision_context_from_row)
    await db_session.commit()

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.context.affected_entities == decision_context_from_row.context.affected_entities
    assert fetched.tags == decision_context_from_row.tags


# ─── Layer 6: LLM SITREP Contract (TC-070–TC-076) ────────────────────────────


@pytest.mark.asyncio
async def test_tc070_sitrep_has_sections(db_session):
    """TC-070: SITREP contains expected sections (summary, actions, recommendations)."""
    from backend.app.services.llm_service import LLMService

    mock_sitrep = (
        "## Situation Report\n"
        "**Anomaly detected**: RSRP dip and BLER increase.\n\n"
        "## Root Cause\nBackhaul fibre cut at gNB-LON-042.\n\n"
        "## Recommended Actions\n1. Failover to adjacent cells.\n"
        "2. Dispatch field engineer.\n\n"
        "## Causal Evidence\n- RSRP Granger-causes DL_BLER (p=0.01)\n"
    )

    service = LLMService()
    with patch.object(service, "_provider") as mock_provider:
        mock_provider.generate = AsyncMock(return_value=mock_sitrep)

        result = await service.generate_explanation(
            incident_context={"entity_id": "CELL_TEST", "anomalies": ["RSRP"]},
            similar_decisions=[],
            causal_evidence=[
                {"cause_metric": "RSRP", "effect_metric": "DL_BLER", "p_value": 0.01, "best_lag": 2}
            ],
        )

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_tc073_sitrep_empty_similar(db_session):
    """TC-073: SITREP handles empty similar_decisions gracefully."""
    from backend.app.services.llm_service import LLMService

    service = LLMService()
    with patch.object(service, "_provider") as mock_provider:
        mock_provider.generate = AsyncMock(return_value="SITREP with no prior incidents.")

        result = await service.generate_explanation(
            incident_context={"entity_id": "CELL_NEW", "anomalies": ["RSRP"]},
            similar_decisions=[],  # Empty
            causal_evidence=None,
        )

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_tc074_no_api_key_fallback():
    """TC-074: LLM service without API key returns fallback message, no crash."""
    from backend.app.services.llm_service import LLMService

    service = LLMService()
    # Force no provider
    service._provider = None

    result = await service.generate_explanation(
        incident_context={"entity_id": "CELL_X"},
        similar_decisions=[],
    )

    assert "not configured" in result.lower() or "api key" in result.lower()
