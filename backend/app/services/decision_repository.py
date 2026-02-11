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
    ReasoningChain,
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
            parent_id=decision.parent_id,
            derivation_type=decision.derivation_type,
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
        if update.parent_id is not None:
            orm_obj.parent_id = update.parent_id
        if update.derivation_type is not None:
            orm_obj.derivation_type = update.derivation_type
        
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
        
        Finding #5: Thresholding is now applied *before* the feedback boost
        to ensure irrelevant decisions are not promoted.
        """
        conditions = []
        if query.tenant_id and query.tenant_id != "global":
            conditions.append(DecisionTraceORM.tenant_id == query.tenant_id)
        
        if query.domain:
            conditions.append(DecisionTraceORM.domain == query.domain)
        
        # Raw similarity calculation (1 - distance)
        raw_similarity = (1 - DecisionTraceORM.embedding.cosine_distance(query_embedding))
        
        # Finding #5: We must query for both ORM and raw_similarity
        result = await self.session.execute(
            select(
                DecisionTraceORM,
                raw_similarity.label("raw_similarity")
            )
            .where(
                and_(
                    *conditions,
                    DecisionTraceORM.embedding.isnot(None),
                    raw_similarity >= query.min_similarity # Filter by threshold FIRST
                )
            )
            .limit(query.limit * 2) # Fetch slightly more to account for re-ranking
        )
        
        rows = result.all()
        
        # Apply feedback boost and re-rank in memory for precision
        scored_results = []
        for orm_obj, sim in rows:
            # Finding #5: Adjusted similarity = raw + (0.1 * feedback_score)
            feedback_boost = 0.1 * orm_obj.feedback_score
            adjusted_sim = sim + feedback_boost
            scored_results.append((self._orm_to_pydantic(orm_obj), adjusted_sim))
            
        # Sort by adjusted similarity
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        return scored_results[:query.limit]
    
    async def record_feedback(
        self,
        decision_id: UUID,
        operator_id: str,
        score: int,
    ) -> bool:
        """
        Finding #4: Records feedback in the junction table and updates the cached aggregate.
        """
        from backend.app.models.decision_trace_orm import DecisionFeedbackORM
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy import func
        from datetime import timezone
        
        # 1. Upsert feedback
        stmt = insert(DecisionFeedbackORM).values(
            decision_id=decision_id,
            operator_id=operator_id,
            score=score,
            created_at=datetime.now(timezone.utc)
        ).on_conflict_do_update(
            index_elements=["decision_id", "operator_id"],
            set_=dict(score=score)
        )
        await self.session.execute(stmt)
        
        # 2. Recalculate aggregate feedback_score
        sum_stmt = select(func.sum(DecisionFeedbackORM.score)).where(
            DecisionFeedbackORM.decision_id == decision_id
        )
        agg_result = await self.session.execute(sum_stmt)
        total_score = agg_result.scalar() or 0
        
        # 3. Update DecisionTraceORM cache
        update_stmt = select(DecisionTraceORM).where(DecisionTraceORM.id == decision_id)
        trace_result = await self.session.execute(update_stmt)
        trace_obj = trace_result.scalar_one_or_none()
        
        if trace_obj:
            trace_obj.feedback_score = total_score
            await self.session.flush()
            return True
        
        return False
    
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

    async def get_reasoning_chain(self, decision_id: UUID) -> ReasoningChain:
        """
        Retrieves the full reasoning chain (lineage) of a decision using recursive CTE.
        Finding M-4 FIX: Removed N+1 re-queries. Returns chain from root to the given decision.
        """
        from sqlalchemy import text
        
        # Recursive SQL CTE to traverse UP the parent hierarchy
        # Note: We query all columns to avoid N+1 fetches later
        sql = text("""
            WITH RECURSIVE reasoning_chain AS (
                -- Anchor member: start with the given decision
                SELECT * FROM decision_traces
                WHERE id = :decision_id
                
                UNION ALL
                
                -- Recursive member: join with parents
                SELECT dt.* FROM decision_traces dt
                INNER JOIN reasoning_chain rc ON dt.id = rc.parent_id
            )
            SELECT * FROM reasoning_chain;
        """)
        
        result = await self.session.execute(sql, {"decision_id": decision_id})
        rows = result.all()
        
        # Convert rows directly to models (Fixes N+1 issue)
        decisions = [self._row_to_pydantic(row) for row in reversed(rows)]
        
        return ReasoningChain(
            decisions=decisions,
            root_id=decisions[0].id if decisions else decision_id,
            length=len(decisions)
        )

    async def get_descendants(self, decision_id: UUID) -> list[DecisionTrace]:
        """
        Retrieves all descendant decisions (follow-ups) triggered by this decision.
        Finding M-4 FIX: Removed N+1 re-queries.
        """
        from sqlalchemy import text
        
        sql = text("""
            WITH RECURSIVE descendants AS (
                SELECT * FROM decision_traces
                WHERE parent_id = :decision_id
                
                UNION ALL
                
                SELECT dt.* FROM decision_traces dt
                INNER JOIN descendants d ON dt.parent_id = d.id
            )
            SELECT * FROM descendants;
        """)
        
        result = await self.session.execute(sql, {"decision_id": decision_id})
        rows = result.all()
        
        return [self._row_to_pydantic(row) for row in rows]

    def _row_to_pydantic(self, row) -> DecisionTrace:
        """Helper to convert a raw SQL row to a Pydantic model."""
        from backend.app.models.decision_trace import (
            Constraint,
            Option,
            DecisionContext,
            DecisionOutcomeRecord,
        )
        import json
        
        # Handle potential string-encoded JSON from raw SQL rows in SQLite/Postgres
        def parse_json(val):
            if isinstance(val, str):
                return json.loads(val)
            return val

        return DecisionTrace(
            id=row.id,
            tenant_id=row.tenant_id,
            created_at=row.created_at,
            decision_made_at=row.decision_made_at,
            trigger_type=row.trigger_type,
            trigger_id=row.trigger_id,
            trigger_description=row.trigger_description,
            context=DecisionContext(**parse_json(row.context)),
            constraints=[Constraint(**c) for c in parse_json(row.constraints)],
            options_considered=[Option(**o) for o in parse_json(row.options_considered)],
            decision_summary=row.decision_summary,
            tradeoff_rationale=row.tradeoff_rationale,
            action_taken=row.action_taken,
            decision_maker=row.decision_maker,
            confidence_score=row.confidence_score,
            outcome=(
                DecisionOutcomeRecord(**parse_json(row.outcome))
                if row.outcome else None
            ),
            embedding=list(row.embedding) if row.embedding is not None else None,
            tags=row.tags,
            domain=row.domain,
            parent_id=row.parent_id,
            derivation_type=row.derivation_type,
        )
    
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
            embedding=list(orm_obj.embedding) if orm_obj.embedding is not None else None,
            tags=orm_obj.tags,
            domain=orm_obj.domain,
            parent_id=orm_obj.parent_id,
            derivation_type=orm_obj.derivation_type,
        )
