import pytest
import os
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.models.decision_trace import DecisionTraceCreate, DecisionContext, SimilarDecisionQuery
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.core.config import get_settings
from backend.app.core.database import Base

settings = get_settings()

@pytest.fixture(scope="module")
def test_engine():
    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/pedkai")
    return create_async_engine(db_url, poolclass=NullPool)

@pytest.fixture(scope="module")
def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(scope="function")
async def e2e_session(test_engine, test_session_factory):
    async with test_session_factory() as session:
        yield session
        await session.rollback()

@pytest.mark.asyncio
async def test_embedding_provider_isolation(e2e_session: AsyncSession):
    repo = DecisionTraceRepository(lambda: e2e_session)
    tenant_id = f"test-tenant-{uuid4().hex[:8]}"
    
    # 1. Create two decisions with different providers but same embedding vector
    vec = [0.1] * settings.embedding_dimension
    
    d1_create = DecisionTraceCreate(
        tenant_id=tenant_id,
        trigger_type="alarm",
        trigger_description="Gemini decision",
        context=DecisionContext(),
        decision_summary="Summary 1",
        tradeoff_rationale="Rationale 1",
        action_taken="Action 1",
        decision_maker="system",
        embedding_provider="gemini",
        embedding_model="text-embedding-004"
    )
    d1 = await repo.create(d1_create, session=e2e_session)
    await repo.set_embedding(d1.id, vec, embedding_provider="gemini", session=e2e_session)
    
    d2_create = DecisionTraceCreate(
        tenant_id=tenant_id,
        trigger_type="alarm",
        trigger_description="MiniLM decision",
        context=DecisionContext(),
        decision_summary="Summary 2",
        tradeoff_rationale="Rationale 2",
        action_taken="Action 2",
        decision_maker="system",
        embedding_provider="minilm",
        embedding_model="all-MiniLM-L6-v2"
    )
    d2 = await repo.create(d2_create, session=e2e_session)
    await repo.set_embedding(d2.id, vec, embedding_provider="minilm", session=e2e_session)
    
    await e2e_session.commit()
    
    # 2. Query for gemini ONLY
    query_gemini = SimilarDecisionQuery(
        tenant_id=tenant_id,
        current_context=DecisionContext(),
        embedding_provider="gemini",
        min_similarity=0.5,
        limit=10
    )
    results_gemini = await repo.find_similar(query_gemini, vec, session=e2e_session)
    
    assert len(results_gemini) == 1
    assert results_gemini[0][0].embedding_provider == "gemini"
    assert results_gemini[0][0].id == d1.id
    
    # 3. Query for minilm ONLY
    query_minilm = SimilarDecisionQuery(
        tenant_id=tenant_id,
        current_context=DecisionContext(),
        embedding_provider="minilm",
        min_similarity=0.5,
        limit=10
    )
    results_minilm = await repo.find_similar(query_minilm, vec, session=e2e_session)
    
    assert len(results_minilm) == 1
    assert results_minilm[0][0].embedding_provider == "minilm"
    assert results_minilm[0][0].id == d2.id
