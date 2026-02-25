"""
Pytest configuration and fixtures.
"""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, Text

# Compliance patch for SQLite (doesn't support JSONB/Vector/UUID natively)
@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(Vector, 'sqlite')
def compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(UUID, 'sqlite')
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.config import get_settings
from backend.app.core.security import get_current_user, oauth2_scheme

# Import all models to register them with Base.metadata (Fix for "No such table" in tests)
from backend.app.models.incident_orm import IncidentORM
from backend.app.models.decision_trace_orm import DecisionTraceORM, DecisionFeedbackORM
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.network_entity_orm import NetworkEntityORM
from backend.app.models.kpi_sample_orm import KpiSampleORM
from backend.app.models.audit_orm import IncidentAuditEntryORM
from backend.app.models.action_execution_orm import ActionExecutionORM
from backend.app.models.tenant_orm import TenantORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.policy_orm import PolicyORM, PolicyEvaluationORM, PolicyVersionORM
from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM
# Note: TMF642 and TMF628 are Pydantic only for now.

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)


@pytest.fixture(scope="session")
def session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the session factory for testing."""
    return TestingSessionLocal


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Creates a fresh database session for a test.
    Rolls back transaction after test completes.
    """
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session
        # Tables are dropped/cleaned by the in-memory nature and create_all above
        # But for safety in complex tests, we could drop all here
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Test client with database dependency overridden.
    """
    # Initialize event bus for P1.6 tests
    from backend.app.events.bus import initialize_event_bus
    initialize_event_bus(maxsize=10000)
    
    async def override_get_db():
        try:
            yield db_session
        finally:
            pass

    async def override_get_metrics_db():
        async with TestingSessionLocal() as session:
            try:
                yield session
                await session.commit()
            finally:
                await session.close()

    from backend.app.core.database import get_db, get_metrics_db
    from backend.app.core.security import get_current_user, oauth2_scheme
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_metrics_db] = override_get_metrics_db
    
    # Auth override
    class MockUser:
        id = "test-user-id"
        username = "test-user"
        tenant_id = "test-tenant"
        role = "admin"
        
    async def override_get_current_user():
        return MockUser()
        
    async def override_oauth2_scheme():
        return "mock-token"
        
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[oauth2_scheme] = override_oauth2_scheme
    
    # Create AsyncClient
    
    # Create AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    
    app.dependency_overrides.clear()
