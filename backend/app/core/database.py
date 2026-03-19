"""Database connection and session management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.app.core.config import get_settings


# Tables that are intentionally global (no per-tenant data).
# PRs that add a table here MUST include a design-review justification.
SYSTEM_TABLES_ALLOWLIST: frozenset[str] = frozenset({
    "tenants",
    "users",
    "user_tenant_access",
    "kpi_dataset_registry",
    "alembic_version",
})


class ArchitectureViolationError(RuntimeError):
    """Raised at class-definition time when a model breaks architectural invariants."""

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
    """Base class for SQLAlchemy models.

    Enforces the architectural invariant that every mapped table must have a
    ``tenant_id`` column (see ``SYSTEM_TABLES_ALLOWLIST`` for exceptions).
    Violations raise ``ArchitectureViolationError`` at import time so the
    application refuses to boot rather than silently leaking cross-tenant data.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        tablename: str | None = getattr(cls, "__tablename__", None)
        if tablename is None or tablename in SYSTEM_TABLES_ALLOWLIST:
            return
        # STI (single-table inheritance) children inherit __tablename__ from
        # the parent.  The parent already passed this check for the shared
        # table, so skip the child to avoid a false ArchitectureViolationError.
        if "__tablename__" not in cls.__dict__:
            return
        col = cls.__dict__.get("tenant_id")
        if col is None:
            raise ArchitectureViolationError(
                f"ORM model '{cls.__name__}' (table='{tablename}') is missing a "
                f"'tenant_id' column. Add:\n"
                f"    tenant_id = Column(String(100), nullable=False, index=True)\n"
                f"or add '{tablename}' to SYSTEM_TABLES_ALLOWLIST in "
                f"backend/app/core/database.py with a design-review justification."
            )
        # Enforce nullable=False when the attribute exposes it (Column objects).
        # declared_attr descriptors don't expose .nullable at class-definition
        # time — the CI test (test_all_tables_have_tenant_id) catches that
        # case via Base.metadata inspection post-mapper-configuration.
        if hasattr(col, "nullable") and col.nullable is not False:
            raise ArchitectureViolationError(
                f"ORM model '{cls.__name__}' (table='{tablename}') declares "
                f"tenant_id as nullable. Must be nullable=False."
            )


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
