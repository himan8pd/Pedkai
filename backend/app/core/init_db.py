"""
Database initialization and migration script.

Creates the PostgreSQL schema with pgvector extension.
Run this to initialize a fresh database.
"""

import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.config import get_settings
from backend.app.core.database import Base
from backend.app.models.decision_trace_orm import DecisionTraceORM  # noqa: F401
from backend.app.models.kpi_orm import KPIMetricORM  # noqa: F401

# Import graph models to register them with Base
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
try:
    from decision_memory.graph_orm import NetworkEntityORM, EntityRelationshipORM  # noqa: F401
except ImportError:
    pass  # Graph models not yet available

settings = get_settings()


async def init_database():
    """Initialize both graph and metrics databases."""
    
    # 1. Initialize Graph Database
    print(f"📡 Initializing Graph Database at {settings.database_url}...")
    graph_engine = create_async_engine(settings.database_url, echo=True)
    async with graph_engine.begin() as conn:
        print("🔧 Enabling pgvector extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("📦 Creating graph tables...")
        # In a real system, we'd filter which tables go where. 
        # For MVP, creating all is fine as long as we use the right engine for the right data.
        await conn.run_sync(Base.metadata.create_all)
    await graph_engine.dispose()
    
    # 2. Initialize Metrics Database (TimescaleDB)
    print(f"📈 Initializing Metrics Database at {settings.metrics_database_url}...")
    metrics_async_engine = create_async_engine(settings.metrics_database_url, echo=True)
    async with metrics_async_engine.begin() as conn:
        print("📦 Creating metrics tables...")
        await conn.run_sync(Base.metadata.create_all)
        
        # Convert to Hypertable (Strategic Review Phase 1 Fix)
        print("⚡ Converting kpi_metrics to TimescaleDB Hypertable...")
        try:
            # We must use text() for the raw command
            # timescale extension might already be enabled in the image, but let's be sure
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
            await conn.execute(text(
                "SELECT create_hypertable('kpi_metrics', 'timestamp', if_not_exists => TRUE)"
            ))

            # 3. Apply Retention Policy (Strategic Review Fix #2)
            print("⏳ Setting 30-day retention policy...")
            await conn.execute(text(
                "SELECT add_retention_policy('kpi_metrics', INTERVAL '30 days', if_not_exists => TRUE)"
            ))

            # 4. Enable Native Compression (Strategic Review Fix #3)
            print("🗜️ Enabling native compression (segmented by entity_id)...")
            await conn.execute(text(
                "ALTER TABLE kpi_metrics SET (timescaledb.compress, timescaledb.compress_segmentby = 'entity_id')"
            ))
            await conn.execute(text(
                "SELECT add_compression_policy('kpi_metrics', INTERVAL '7 days', if_not_exists => TRUE)"
            ))

        except Exception as e:
            print(f"⚠️ Could not apply TimescaleDB optimizations: {e}")

    await metrics_async_engine.dispose()
    print("✅ All databases initialized successfully!")


async def drop_all_tables():
    """Drop all tables (use with caution!)."""
    
    engine = create_async_engine(settings.database_url, echo=True)
    
    async with engine.begin() as conn:
        print("⚠️ Dropping all tables...")
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()
    print("✅ All tables dropped.")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--drop":
        print("⚠️ WARNING: This will drop all tables!")
        confirm = input("Type 'yes' to confirm: ")
        if confirm == "yes":
            asyncio.run(drop_all_tables())
        else:
            print("Aborted.")
    else:
        asyncio.run(init_database())
