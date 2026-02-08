"""
Decision Trace Repository - Database operations for decision traces.

Handles CRUD operations and similarity search using PostgreSQL + pgvector.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.decision_trace import (
    DecisionTrace,
    DecisionTraceCreate,
    DecisionTraceUpdate,
    DecisionContext,
    DecisionOutcomeRecord,
    SimilarDecisionQuery,
)
from backend.app.models.decision_trace_orm import DecisionTraceORM


class DecisionTraceRepository:
    """Repository for Decision Trace database operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, decision: DecisionTraceCreate) -> DecisionTrace:
        """Create a new decision trace in the database."""
        orm_obj = DecisionTraceORM(
            tenant_id=decision.tenant_id,
            trigger_type=decision.trigger_type,
            trigger_id=decision.trigger_id,
            trigger_description=decision.trigger_description,
            context=decision.context.model_dump(),
            constraints=[c.model_dump() for c in decision.constraints],
            options_considered=[o.model_dump() for o in decision.options_considered],
            decision_summary=decision.decision_summary,
            tradeoff_rationale=decision.tradeoff_rationale,
            action_taken=decision.action_taken,
            decision_maker=decision.decision_maker,
            confidence_score=decision.confidence_score,
            domain=decision.domain,
            tags=decision.tags,
        )
        
        self.session.add(orm_obj)
        await self.session.flush()
        await self.session.refresh(orm_obj)
        
        return self._orm_to_pydantic(orm_obj)
    
    async def get_by_id(self, decision_id: UUID) -> Optional[DecisionTrace]:
        """Get a decision trace by its ID."""
        result = await self.session.execute(
            select(DecisionTraceORM).where(DecisionTraceORM.id == decision_id)
        )
        orm_obj = result.scalar_one_or_none()
        
        if orm_obj is None:
            return None
        
        return self._orm_to_pydantic(orm_obj)
    
    async def update(
        self,
        decision_id: UUID,
        update: DecisionTraceUpdate,
    ) -> Optional[DecisionTrace]:
        """Update a decision trace."""
        result = await self.session.execute(
            select(DecisionTraceORM).where(DecisionTraceORM.id == decision_id)
        )
        orm_obj = result.scalar_one_or_none()
        
        if orm_obj is None:
            return None
        
        if update.outcome is not None:
            orm_obj.outcome = update.outcome.model_dump()
        if update.tags is not None:
            orm_obj.tags = update.tags
        
        await self.session.flush()
        await self.session.refresh(orm_obj)
        
        return self._orm_to_pydantic(orm_obj)
    
    async def list_decisions(
        self,
        tenant_id: str,
        domain: Optional[str] = None,
        trigger_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DecisionTrace]:
        """List decision traces with filtering."""
        conditions = [DecisionTraceORM.tenant_id == tenant_id]
        
        if domain is not None:
            conditions.append(DecisionTraceORM.domain == domain)
        if trigger_type is not None:
            conditions.append(DecisionTraceORM.trigger_type == trigger_type)
        
        result = await self.session.execute(
            select(DecisionTraceORM)
            .where(and_(*conditions))
            .order_by(desc(DecisionTraceORM.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        orm_objects = result.scalars().all()
        return [self._orm_to_pydantic(obj) for obj in orm_objects]
    
    async def find_similar(
        self,
        query: SimilarDecisionQuery,
        query_embedding: list[float],
    ) -> list[tuple[DecisionTrace, float]]:
        """
        Find similar decisions using pgvector cosine similarity.
        
        Returns list of (decision, similarity_score) tuples.
        """
        conditions = [DecisionTraceORM.tenant_id == query.tenant_id]
        
        if query.domain:
            conditions.append(DecisionTraceORM.domain == query.domain)
        
        # pgvector cosine distance (lower = more similar)
        # We convert to similarity: 1 - distance
        result = await self.session.execute(
            select(
                DecisionTraceORM,
                (1 - DecisionTraceORM.embedding.cosine_distance(query_embedding)).label("similarity")
            )
            .where(
                and_(
                    *conditions,
                    DecisionTraceORM.embedding.isnot(None),
                )
            )
            .order_by(DecisionTraceORM.embedding.cosine_distance(query_embedding))
            .limit(query.limit)
        )
        
        rows = result.all()
        
        # Filter by minimum similarity threshold
        return [
            (self._orm_to_pydantic(row[0]), row[1])
            for row in rows
            if row[1] >= query.min_similarity
        ]
    
    async def set_embedding(
        self,
        decision_id: UUID,
        embedding: list[float],
    ) -> bool:
        """Set the embedding vector for a decision trace."""
        result = await self.session.execute(
            select(DecisionTraceORM).where(DecisionTraceORM.id == decision_id)
        )
        orm_obj = result.scalar_one_or_none()
        
        if orm_obj is None:
            return False
        
        orm_obj.embedding = embedding
        await self.session.flush()
        
        return True
    
    def _orm_to_pydantic(self, orm_obj: DecisionTraceORM) -> DecisionTrace:
        """Convert ORM object to Pydantic model."""
        from backend.app.models.decision_trace import (
            Constraint,
            Option,
            DecisionContext,
            DecisionOutcomeRecord,
        )
        
        return DecisionTrace(
            id=orm_obj.id,
            tenant_id=orm_obj.tenant_id,
            created_at=orm_obj.created_at,
            decision_made_at=orm_obj.decision_made_at,
            trigger_type=orm_obj.trigger_type,
            trigger_id=orm_obj.trigger_id,
            trigger_description=orm_obj.trigger_description,
            context=DecisionContext(**orm_obj.context),
            constraints=[Constraint(**c) for c in orm_obj.constraints],
            options_considered=[Option(**o) for o in orm_obj.options_considered],
            decision_summary=orm_obj.decision_summary,
            tradeoff_rationale=orm_obj.tradeoff_rationale,
            action_taken=orm_obj.action_taken,
            decision_maker=orm_obj.decision_maker,
            confidence_score=orm_obj.confidence_score,
            outcome=(
                DecisionOutcomeRecord(**orm_obj.outcome)
                if orm_obj.outcome else None
            ),
            embedding=list(orm_obj.embedding) if orm_obj.embedding else None,
            tags=orm_obj.tags,
            domain=orm_obj.domain,
        )
