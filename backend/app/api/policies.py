"""
Policy API Endpoints (P5.1)

Routes for managing policies and evaluating autonomous actions.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
import uuid
from datetime import datetime

from backend.app.core.database import get_db
from backend.app.core.security import Security, get_current_user
from backend.app.models.policy_orm import PolicyORM, PolicyEvaluationORM, PolicyVersionORM
from backend.app.schemas.policies import (
    PolicyCreate,
    PolicyUpdate,
    PolicyResponse,
    PolicyEvaluationRequest,
    PolicyEvaluationResponse,
    PolicyAuditEntry,
    PolicyVersionResponse,
)
from backend.app.services.policy_engine import get_policy_engine

router = APIRouter(prefix="/api/v1/policies", tags=["Policies"])


@router.post("/{tenant_id}", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    tenant_id: str,
    policy: PolicyCreate,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> PolicyResponse:
    """
    P5.1: Create a new policy for autonomous execution gating.
    
    Only tenant admins can create policies.
    """
    # Check authorization (must be tenant admin or platform admin)
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Create new policy
    policy_id = str(uuid.uuid4())
    new_policy = PolicyORM(
        id=policy_id,
        tenant_id=tenant_id,
        name=policy.name,
        description=policy.description,
        version=1,
        status="active",
        rules=policy.rules.dict(),
        created_by=policy.created_by or current_user.email,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    session.add(new_policy)
    await session.flush()
    
    # Create first version record
    version = PolicyVersionORM(
        id=str(uuid.uuid4()),
        policy_id=policy_id,
        tenant_id=tenant_id,
        version_number=1,
        rules=policy.rules.dict(),
        modified_by=policy.created_by or current_user.email,
        modified_at=datetime.utcnow(),
        change_reason="Initial policy creation",
    )
    session.add(version)
    await session.commit()
    
    return PolicyResponse.from_orm(new_policy)


@router.get("/{tenant_id}", response_model=List[PolicyResponse])
async def list_policies(
    tenant_id: str,
    status_filter: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> List[PolicyResponse]:
    """
    P5.1: List all policies for a tenant (active by default).
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Build query
    query = select(PolicyORM).where(PolicyORM.tenant_id == tenant_id)
    
    if status_filter:
        query = query.where(PolicyORM.status == status_filter)
    else:
        query = query.where(PolicyORM.status == "active")
    
    query = query.order_by(desc(PolicyORM.updated_at))
    
    result = await session.execute(query)
    policies = result.scalars().all()
    
    return [PolicyResponse.from_orm(p) for p in policies]


@router.get("/{tenant_id}/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    tenant_id: str,
    policy_id: str,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> PolicyResponse:
    """
    P5.1: Retrieve a specific policy.
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    result = await session.execute(
        select(PolicyORM).where(
            (PolicyORM.id == policy_id) & (PolicyORM.tenant_id == tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    
    return PolicyResponse.from_orm(policy)


@router.patch("/{tenant_id}/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    tenant_id: str,
    policy_id: str,
    update: PolicyUpdate,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> PolicyResponse:
    """
    P5.1: Update a policy (creates new version).
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Get existing policy
    result = await session.execute(
        select(PolicyORM).where(
            (PolicyORM.id == policy_id) & (PolicyORM.tenant_id == tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    
    # Archive current rules as version
    if update.rules or update.name or update.description:
        archive_version = PolicyVersionORM(
            id=str(uuid.uuid4()),
            policy_id=policy_id,
            tenant_id=tenant_id,
            version_number=policy.version,
            rules=policy.rules,
            modified_by=update.modified_by or current_user.email,
            modified_at=datetime.utcnow(),
            change_reason=update.change_reason,
        )
        session.add(archive_version)
    
    # Update fields
    if update.name:
        policy.name = update.name
    if update.description is not None:
        policy.description = update.description
    if update.rules:
        policy.rules = update.rules.dict()
        policy.version += 1
    if update.status:
        policy.status = update.status
    
    policy.updated_at = datetime.utcnow()
    
    await session.commit()
    return PolicyResponse.from_orm(policy)


@router.post("/{tenant_id}/evaluate", response_model=PolicyEvaluationResponse)
async def evaluate_action(
    tenant_id: str,
    request: PolicyEvaluationRequest,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> PolicyEvaluationResponse:
    """
    P5.1: Pre-evaluate if an autonomous action is permitted.
    
    This is the Policy Gate in the safety rails pipeline (P5.3).
    Returns detailed evaluation record for audit trail.
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Get policy engine and evaluate
    policy_engine = get_policy_engine()
    
    # Generate trace ID for distributed tracing
    import uuid
    trace_id = str(uuid.uuid4())
    
    # Evaluate action through v2 pipeline
    decision = await policy_engine.evaluate_autonomous_action(
        session=session,
        tenant_id=tenant_id,
        action_type=request.action_type,
        entity_id=request.entity_id,
        affected_entity_count=request.affected_entity_count or 1,
        action_parameters=request.action_parameters,
        trace_id=trace_id,
        confidence_score=0.8,  # Placeholder; would come from Decision Memory
    )
    
    return PolicyEvaluationResponse(
        decision=decision.decision,
        confidence=decision.confidence,
        matched_rules=decision.matched_rules,
        reason=decision.reason,
        trace_id=trace_id,
        recommended_confirmation_window_sec=decision.recommended_confirmation_window_sec,
    )


@router.get("/{tenant_id}/{policy_id}/audit-trail", response_model=List[PolicyAuditEntry])
async def get_policy_audit_trail(
    tenant_id: str,
    policy_id: str,
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> List[PolicyAuditEntry]:
    """
    P5.1: Retrieve audit trail for a policy.
    
    Shows all evaluations and decisions made with this policy.
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Verify policy exists
    policy_result = await session.execute(
        select(PolicyORM).where(
            (PolicyORM.id == policy_id) & (PolicyORM.tenant_id == tenant_id)
        )
    )
    if not policy_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    
    # Get evaluations
    result = await session.execute(
        select(PolicyEvaluationORM)
        .where((PolicyEvaluationORM.policy_id == policy_id) & (PolicyEvaluationORM.tenant_id == tenant_id))
        .order_by(desc(PolicyEvaluationORM.evaluated_at))
        .limit(limit)
    )
    evaluations = result.scalars().all()
    
    return [PolicyAuditEntry.from_orm(e) for e in evaluations]


@router.get("/{tenant_id}/{policy_id}/versions", response_model=List[PolicyVersionResponse])
async def get_policy_versions(
    tenant_id: str,
    policy_id: str,
    session: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    security: Security = Depends(Security),
) -> List[PolicyVersionResponse]:
    """
    P5.1: Retrieve version history for a policy.
    """
    # Verify authorization
    if current_user.tenant_id != tenant_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized")
    
    # Verify policy exists
    policy_result = await session.execute(
        select(PolicyORM).where(
            (PolicyORM.id == policy_id) & (PolicyORM.tenant_id == tenant_id)
        )
    )
    if not policy_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    
    # Get versions
    result = await session.execute(
        select(PolicyVersionORM)
        .where((PolicyVersionORM.policy_id == policy_id) & (PolicyVersionORM.tenant_id == tenant_id))
        .order_by(desc(PolicyVersionORM.version_number))
    )
    versions = result.scalars().all()
    
    return [PolicyVersionResponse.from_orm(v) for v in versions]
