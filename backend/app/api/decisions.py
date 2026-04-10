"""
Decision Trace API endpoints.

Provides CRUD operations, semantic search (pgvector), and RLHF feedback
for decision traces stored in PostgreSQL.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.config import get_settings
from backend.app.core.database import get_db, async_session_maker
from backend.app.models.decision_trace import (
    DecisionTrace,
    DecisionTraceCreate,
    DecisionTraceUpdate,
    DecisionOutcomeRecord,
    SimilarDecisionQuery,
    ReasoningChain,
)
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.embedding_service import get_embedding_service
from backend.app.services.rl_evaluator import get_rl_evaluator

router = APIRouter()
settings = get_settings()


@router.post("", response_model=DecisionTrace, status_code=201)
async def create_decision_trace(
    decision: DecisionTraceCreate,
    db=Depends(get_db),
) -> DecisionTrace:
    """
    Create a new decision trace.

    Captures the full reasoning chain for a decision:
    - Context available at decision time
    - Constraints that were binding
    - Options that were considered
    - The tradeoff made and why
    """
    repo = DecisionTraceRepository(async_session_maker)

    # Idempotency: check for duplicate trigger_id within same tenant
    if decision.trigger_id and decision.tenant_id:
        from sqlalchemy import select
        from backend.app.models.decision_trace_orm import DecisionTraceORM
        dup_result = await db.execute(
            select(DecisionTraceORM).where(
                DecisionTraceORM.tenant_id == decision.tenant_id,
                DecisionTraceORM.trigger_id == decision.trigger_id,
                DecisionTraceORM.trigger_type == decision.trigger_type,
            ).limit(1)
        )
        existing = dup_result.scalar_one_or_none()
        if existing:
            return DecisionTrace.model_validate(existing, from_attributes=True)

    trace = await repo.create(decision)

    # Generate and store embedding for similarity search
    embedding_service = get_embedding_service()
    embedding_text = embedding_service.create_decision_text(
        trigger_description=decision.trigger_description,
        decision_summary=decision.decision_summary,
        tradeoff_rationale=decision.tradeoff_rationale,
        action_taken=decision.action_taken,
    )
    embedding = await embedding_service.generate_embedding(embedding_text)

    if embedding:
        await repo.set_embedding(trace.id, embedding)
        trace.embedding = embedding

    return trace


@router.get("", response_model=list[DecisionTrace])
async def list_decision_traces(
    tenant_id: str,
    domain: Optional[str] = None,
    trigger_type: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
) -> list[DecisionTrace]:
    """
    List decision traces with filtering.

    Returns decisions for a specific tenant, optionally filtered by domain
    and trigger type.
    """
    repo = DecisionTraceRepository(async_session_maker)
    return await repo.list_decisions(
        tenant_id=tenant_id,
        domain=domain,
        trigger_type=trigger_type,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=list[DecisionTrace])
async def search_decisions(
    q: str = Query(..., min_length=3),
    tenant_id: str = "global" if settings.memory_search_global_default else settings.default_tenant_id,
    limit: int = Query(default=settings.memory_search_limit, ge=1, le=20),
    min_similarity: float = Query(default=settings.memory_search_min_similarity, ge=0.0, le=1.0),
    db=Depends(get_db),
) -> list[DecisionTrace]:
    """
    Search for similar decisions using semi-natural language.

    Convenience endpoint for simple semantic search.
    Default search is 'global' across all tenants for the operator view.
    Threshold is 0.0 by default to always return the most relevant matches.
    """
    repo = DecisionTraceRepository(async_session_maker)
    embedding_service = get_embedding_service()

    # In search mode, we just embed the query string directly
    # as if it were a trigger description
    query_embedding = await embedding_service.generate_embedding(q)

    if query_embedding:
        # Create a mock query object for the repository
        from backend.app.models.decision_trace import DecisionContext
        mock_query = SimilarDecisionQuery(
            tenant_id=tenant_id,
            current_context=DecisionContext(trigger_description=q),
            limit=limit,
            min_similarity=min_similarity
        )
        results = await repo.find_similar(mock_query, query_embedding)
        return [trace for trace, _ in results]

    return []


@router.patch("/{decision_id}", response_model=DecisionTrace)
async def update_decision_trace(
    decision_id: UUID,
    update: DecisionTraceUpdate,
    db=Depends(get_db),
) -> DecisionTrace:
    """
    Update a decision trace.

    Primarily used to record the outcome after the action was taken.
    """
    repo = DecisionTraceRepository(async_session_maker)
    trace = await repo.update(decision_id, update)
    if trace is None:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    return trace


@router.get("/{decision_id}", response_model=DecisionTrace)
async def get_decision_trace(
    decision_id: UUID,
    db=Depends(get_db),
) -> DecisionTrace:
    """Get a decision trace by ID."""
    repo = DecisionTraceRepository(async_session_maker)
    trace = await repo.get_by_id(decision_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    return trace


@router.post("/similar", response_model=list[DecisionTrace])
async def find_similar_decisions(
    query: SimilarDecisionQuery,
    db=Depends(get_db),
) -> list[DecisionTrace]:
    """
    Find similar past decisions based on context.

    This is the core "Have we seen this before?" query that enables
    learning from past decisions.

    Uses pgvector for semantic similarity when database is configured.
    """
    repo = DecisionTraceRepository(async_session_maker)
    embedding_service = get_embedding_service()

    # Create text representation of current context
    context_text = embedding_service.create_decision_text(
        trigger_description=f"Context: {query.current_context.alarm_ids}",
        decision_summary="Finding similar decisions",
        tradeoff_rationale="",
        action_taken="",
        context_description=str(query.current_context.affected_entities),
    )

    query_embedding = await embedding_service.generate_embedding(context_text)

    if query_embedding:
        results = await repo.find_similar(query, query_embedding)
        return [trace for trace, _ in results]
    else:
        # Fallback to listing recent decisions if embedding fails
        return await repo.list_decisions(
            tenant_id=query.tenant_id,
            domain=query.domain,
            limit=query.limit,
        )


@router.post("/{decision_id}/outcome", response_model=DecisionTrace)
async def record_outcome(
    decision_id: UUID,
    outcome: DecisionOutcomeRecord,
    db=Depends(get_db),
) -> DecisionTrace:
    """
    Record the outcome of a decision.

    This closes the feedback loop - we learn what worked and what didn't.
    """
    update = DecisionTraceUpdate(outcome=outcome)
    trace = await update_decision_trace(decision_id, update, db)

    # Phase 15.4: Trigger RL Evaluator
    try:
        evaluator = get_rl_evaluator(db)
        reward = await evaluator.evaluate_decision_outcome(trace)
        if reward != 0:
            await evaluator.apply_feedback(trace.id, reward)
            trace = await get_decision_trace(decision_id, db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"RL Evaluator failed for decision {decision_id}: {e}")

    return trace


# ====================================================================
# Operator Feedback Endpoints (RLHF)
# ====================================================================

@router.post("/{decision_id}/upvote", status_code=200)
async def upvote_decision(
    decision_id: UUID,
    db=Depends(get_db),
) -> dict:
    """
    Mark a decision as helpful.

    Finding #4: Multi-operator aggregation prevents gaming.
    """
    repo = DecisionTraceRepository(async_session_maker)
    # Mocking operator_id as "operator_1" for now (finding #4)
    success = await repo.record_feedback(decision_id, operator_id="operator_1", score=1)
    if not success:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    await db.commit()
    return {"status": "upvoted", "decision_id": str(decision_id)}


@router.post("/{decision_id}/downvote", status_code=200)
async def downvote_decision(
    decision_id: UUID,
    db=Depends(get_db),
) -> dict:
    """
    Mark a decision as unhelpful or incorrect.

    Finding #4: Negative feedback penalizes this decision in future similarity searches.
    """
    repo = DecisionTraceRepository(async_session_maker)
    # Mocking operator_id as "operator_1" for now (finding #4)
    success = await repo.record_feedback(decision_id, operator_id="operator_1", score=-1)
    if not success:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    await db.commit()
    return {"status": "downvoted", "decision_id": str(decision_id)}
