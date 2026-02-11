"""Database connection and session management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.app.core.config import get_settings

settings = get_settings()

# Create async engine
engine_kwargs = {"echo": settings.debug}

# SSL Configuration
connect_args = {}
if settings.db_ssl_mode == "require":
    connect_args["ssl"] = "require"
    
if connect_args:
    engine_kwargs["connect_args"] = connect_args

if "postgresql" in settings.database_url:
    engine_kwargs.update({
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_pre_ping": True, # Resilience fix
    })

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Create async engine for metrics
metrics_kwargs = {"echo": settings.debug}

# SSL Configuration for Metrics
if connect_args:
    metrics_kwargs["connect_args"] = connect_args

if "postgresql" in settings.metrics_database_url:
    metrics_kwargs.update({
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_pre_ping": True, # Resilience fix
    })

metrics_engine = create_async_engine(
    settings.metrics_database_url,
    **metrics_kwargs
)

# Metrics Session factory
metrics_session_maker = async_sessionmaker(
    metrics_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_metrics_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting metrics database sessions."""
    async with metrics_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_metrics_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for metrics database sessions."""
    async with metrics_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
