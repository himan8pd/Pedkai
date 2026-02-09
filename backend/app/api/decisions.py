"""
Decision Trace API endpoints.

Supports both in-memory mode (for quick testing) and
PostgreSQL mode (for production with pgvector).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.models.decision_trace import (
    DecisionTrace,
    DecisionTraceCreate,
    DecisionTraceUpdate,
    DecisionOutcomeRecord,
    SimilarDecisionQuery,
)
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.embedding_service import get_embedding_service

router = APIRouter()
settings = get_settings()

# In-memory store for MVP mode (when no DB configured)
_decision_store: dict[UUID, DecisionTrace] = {}

# Flag to determine storage mode
USE_DATABASE = "localhost" not in settings.database_url or True  # Set to False for in-memory mode


@router.post("/", response_model=DecisionTrace, status_code=201)
async def create_decision_trace(
    decision: DecisionTraceCreate,
    db=Depends(get_db) if USE_DATABASE else None,
) -> DecisionTrace:
    """
    Create a new decision trace.
    
    Captures the full reasoning chain for a decision:
    - Context available at decision time
    - Constraints that were binding
    - Options that were considered
    - The tradeoff made and why
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
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
    else:
        # In-memory fallback
        trace = DecisionTrace(
            tenant_id=decision.tenant_id,
            trigger_type=decision.trigger_type,
            trigger_id=decision.trigger_id,
            trigger_description=decision.trigger_description,
            context=decision.context,
            constraints=decision.constraints,
            options_considered=decision.options_considered,
            decision_summary=decision.decision_summary,
            tradeoff_rationale=decision.tradeoff_rationale,
            action_taken=decision.action_taken,
            decision_maker=decision.decision_maker,
            confidence_score=decision.confidence_score,
            domain=decision.domain,
            tags=decision.tags,
        )
        _decision_store[trace.id] = trace
        return trace


@router.get("/", response_model=list[DecisionTrace])
async def list_decision_traces(
    tenant_id: str,
    domain: Optional[str] = None,
    trigger_type: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db) if USE_DATABASE else None,
) -> list[DecisionTrace]:
    """
    List decision traces with filtering.
    
    Returns decisions for a specific tenant, optionally filtered by domain
    and trigger type.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        return await repo.list_decisions(
            tenant_id=tenant_id,
            domain=domain,
            trigger_type=trigger_type,
            limit=limit,
            offset=offset,
        )
    else:
        results = [
            trace for trace in _decision_store.values()
            if trace.tenant_id == tenant_id
            and (domain is None or trace.domain == domain)
            and (trigger_type is None or trace.trigger_type == trigger_type)
        ]
        results.sort(key=lambda x: x.created_at, reverse=True)
        return results[offset:offset + limit]


@router.get("/search", response_model=list[DecisionTrace])
async def search_decisions(
    q: str = Query(..., min_length=3),
    tenant_id: str = "global" if settings.memory_search_global_default else settings.default_tenant_id,
    limit: int = Query(default=settings.memory_search_limit, ge=1, le=20),
    min_similarity: float = Query(default=settings.memory_search_min_similarity, ge=0.0, le=1.0),
    db=Depends(get_db) if USE_DATABASE else None,
) -> list[DecisionTrace]:
    """
    Search for similar decisions using semi-natural language.
    
    Convenience endpoint for simple semantic search.
    Default search is 'global' across all tenants for the operator view.
    Threshold is 0.0 by default to always return the most relevant matches.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        embedding_service = get_embedding_service()
        
        # In search mode, we just embed the query string directly 
        # as if it were a trigger description
        query_embedding = await embedding_service.generate_embedding(q)
        
        if query_embedding:
            # Create a mock query object for the repository
            from backend.app.models.decision_trace import DecisionContext
            mock_query = SimilarDecisionQuery(
                tenant_id=tenant_id,
                current_context=DecisionContext(trigger_description=q), # Fallback usage
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
    db=Depends(get_db) if USE_DATABASE else None,
) -> DecisionTrace:
    """
    Update a decision trace.
    
    Primarily used to record the outcome after the action was taken.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        trace = await repo.update(decision_id, update)
        if trace is None:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        return trace
    else:
        if decision_id not in _decision_store:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        
        trace = _decision_store[decision_id]
        
        if update.outcome is not None:
            trace.outcome = update.outcome
        if update.tags is not None:
            trace.tags = update.tags
        
        _decision_store[decision_id] = trace
        return trace


@router.get("/{decision_id}", response_model=DecisionTrace)
async def get_decision_trace(
    decision_id: UUID,
    db=Depends(get_db) if USE_DATABASE else None,
) -> DecisionTrace:
    """Get a decision trace by ID."""
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        trace = await repo.get_by_id(decision_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        return trace
    else:
        if decision_id not in _decision_store:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        return _decision_store[decision_id]


@router.post("/similar", response_model=list[DecisionTrace])
async def find_similar_decisions(
    query: SimilarDecisionQuery,
    db=Depends(get_db) if USE_DATABASE else None,
) -> list[DecisionTrace]:
    """
    Find similar past decisions based on context.
    
    This is the core "Have we seen this before?" query that enables
    learning from past decisions.
    
    Uses pgvector for semantic similarity when database is configured.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
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
    else:
        # In-memory fallback with simple overlap scoring
        current_alarms = set(query.current_context.alarm_ids)
        current_entities = set(query.current_context.affected_entities)
        
        scored_results = []
        
        for trace in _decision_store.values():
            if trace.tenant_id != query.tenant_id:
                continue
            if query.domain and trace.domain != query.domain:
                continue
            
            trace_alarms = set(trace.context.alarm_ids)
            trace_entities = set(trace.context.affected_entities)
            
            alarm_overlap = len(current_alarms & trace_alarms)
            entity_overlap = len(current_entities & trace_entities)
            
            total_current = len(current_alarms) + len(current_entities)
            if total_current > 0:
                similarity = (alarm_overlap + entity_overlap) / total_current
            else:
                similarity = 0.0
            
            if similarity >= query.min_similarity:
                scored_results.append((similarity, trace))
        
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [trace for _, trace in scored_results[:query.limit]]


@router.post("/{decision_id}/outcome", response_model=DecisionTrace)
async def record_outcome(
    decision_id: UUID,
    outcome: DecisionOutcomeRecord,
    db=Depends(get_db) if USE_DATABASE else None,
) -> DecisionTrace:
    """
    Record the outcome of a decision.
    
    This closes the feedback loop - we learn what worked and what didn't.
    """
    update = DecisionTraceUpdate(outcome=outcome)
    return await update_decision_trace(decision_id, update, db)


# ====================================================================
# Operator Feedback Endpoints (RLHF)
# ====================================================================

@router.post("/{decision_id}/upvote", status_code=200)
async def upvote_decision(
    decision_id: UUID,
    db=Depends(get_db) if USE_DATABASE else None,
) -> dict:
    """
    Mark a decision as helpful.
    
    Finding #4: Multi-operator aggregation prevents gaming.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        # Mocking operator_id as "operator_1" for now (finding #4)
        success = await repo.record_feedback(decision_id, operator_id="operator_1", score=1)
        if not success:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        await db.commit()
        return {"status": "upvoted", "decision_id": str(decision_id)}
    else:
        if decision_id not in _decision_store:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        return {"status": "upvoted (in-memory mode)", "decision_id": str(decision_id)}


@router.post("/{decision_id}/downvote", status_code=200)
async def downvote_decision(
    decision_id: UUID,
    db=Depends(get_db) if USE_DATABASE else None,
) -> dict:
    """
    Mark a decision as unhelpful or incorrect.
    
    Finding #4: Negative feedback penalizes this decision in future similarity searches.
    """
    if USE_DATABASE and db:
        repo = DecisionTraceRepository(db)
        # Mocking operator_id as "operator_1" for now (finding #4)
        success = await repo.record_feedback(decision_id, operator_id="operator_1", score=-1)
        if not success:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        await db.commit()
        return {"status": "downvoted", "decision_id": str(decision_id)}
    else:
        if decision_id not in _decision_store:
            raise HTTPException(status_code=404, detail="Decision trace not found")
        return {"status": "downvoted (in-memory mode)", "decision_id": str(decision_id)}
