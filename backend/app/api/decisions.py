"""Decision Trace API endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from backend.app.models.decision_trace import (
    DecisionTrace,
    DecisionTraceCreate,
    DecisionTraceUpdate,
    DecisionOutcomeRecord,
    SimilarDecisionQuery,
)

router = APIRouter()

# In-memory store for MVP (will be replaced with PostgreSQL)
_decision_store: dict[UUID, DecisionTrace] = {}


@router.post("/", response_model=DecisionTrace, status_code=201)
async def create_decision_trace(decision: DecisionTraceCreate) -> DecisionTrace:
    """
    Create a new decision trace.
    
    This captures the full reasoning chain for a decision:
    - Context available at decision time
    - Constraints that were binding
    - Options that were considered
    - The tradeoff made and why
    """
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


@router.get("/{decision_id}", response_model=DecisionTrace)
async def get_decision_trace(decision_id: UUID) -> DecisionTrace:
    """Get a decision trace by ID."""
    if decision_id not in _decision_store:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    return _decision_store[decision_id]


@router.patch("/{decision_id}", response_model=DecisionTrace)
async def update_decision_trace(
    decision_id: UUID, 
    update: DecisionTraceUpdate
) -> DecisionTrace:
    """
    Update a decision trace.
    
    Primarily used to record the outcome after the action was taken.
    """
    if decision_id not in _decision_store:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    
    trace = _decision_store[decision_id]
    
    if update.outcome is not None:
        trace.outcome = update.outcome
    if update.tags is not None:
        trace.tags = update.tags
    
    _decision_store[decision_id] = trace
    return trace


@router.get("/", response_model=list[DecisionTrace])
async def list_decision_traces(
    tenant_id: str,
    domain: Optional[str] = None,
    trigger_type: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[DecisionTrace]:
    """
    List decision traces with filtering.
    
    Returns decisions for a specific tenant, optionally filtered by domain
    and trigger type.
    """
    results = [
        trace for trace in _decision_store.values()
        if trace.tenant_id == tenant_id
        and (domain is None or trace.domain == domain)
        and (trigger_type is None or trace.trigger_type == trigger_type)
    ]
    
    # Sort by creation time, newest first
    results.sort(key=lambda x: x.created_at, reverse=True)
    
    return results[offset:offset + limit]


@router.post("/similar", response_model=list[DecisionTrace])
async def find_similar_decisions(query: SimilarDecisionQuery) -> list[DecisionTrace]:
    """
    Find similar past decisions based on context.
    
    This is the core "Have we seen this before?" query that enables
    learning from past decisions,
    
    TODO: Implement vector similarity search with pgvector
    """
    # For MVP, return decisions with overlapping alarm IDs or affected entities
    current_alarms = set(query.current_context.alarm_ids)
    current_entities = set(query.current_context.affected_entities)
    
    scored_results = []
    
    for trace in _decision_store.values():
        if trace.tenant_id != query.tenant_id:
            continue
        if query.domain and trace.domain != query.domain:
            continue
        
        # Simple overlap scoring (will be replaced with vector similarity)
        trace_alarms = set(trace.context.alarm_ids)
        trace_entities = set(trace.context.affected_entities)
        
        alarm_overlap = len(current_alarms & trace_alarms)
        entity_overlap = len(current_entities & trace_entities)
        
        # Naive similarity score
        total_current = len(current_alarms) + len(current_entities)
        if total_current > 0:
            similarity = (alarm_overlap + entity_overlap) / total_current
        else:
            similarity = 0.0
        
        if similarity >= query.min_similarity:
            scored_results.append((similarity, trace))
    
    # Sort by similarity, highest first
    scored_results.sort(key=lambda x: x[0], reverse=True)
    
    return [trace for _, trace in scored_results[:query.limit]]


@router.post("/{decision_id}/outcome", response_model=DecisionTrace)
async def record_outcome(
    decision_id: UUID,
    outcome: DecisionOutcomeRecord,
) -> DecisionTrace:
    """
    Record the outcome of a decision.
    
    This closes the feedback loop - we learn what worked and what didn't.
    """
    if decision_id not in _decision_store:
        raise HTTPException(status_code=404, detail="Decision trace not found")
    
    trace = _decision_store[decision_id]
    trace.outcome = outcome
    _decision_store[decision_id] = trace
    
    return trace
