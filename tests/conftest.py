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
    async def override_get_db():
        try:
            yield db_session
        finally:
            pass

    async def override_get_user():
        from backend.app.core.security import User, Role
        return User(
            username="testuser", 
            role=Role.OPERATOR, 
            scopes=["tmf642:alarm:write", "tmf642:alarm:read"]
        )

    async def override_oauth2_scheme():
        return "dummy-token"

    async def override_get_metrics_db():
        async with TestingSessionLocal() as session:
            try:
                yield session
                await session.commit()
            finally:
                await session.close()

    from backend.app.core.database import get_db, get_metrics_db
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_metrics_db] = override_get_metrics_db
    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[oauth2_scheme] = override_oauth2_scheme
    
    # Create AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    
    app.dependency_overrides.clear()
