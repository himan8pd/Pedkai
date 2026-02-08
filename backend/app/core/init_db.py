"""
Database initialization and migration script.

Creates the PostgreSQL schema with pgvector extension.
Run this to initialize a fresh database.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.config import get_settings
from backend.app.core.database import Base
from backend.app.models.decision_trace_orm import DecisionTraceORM  # noqa: F401

settings = get_settings()


async def init_database():
    """Initialize the database with pgvector extension and tables."""
    
    engine = create_async_engine(settings.database_url, echo=True)
    
    async with engine.begin() as conn:
        # Enable pgvector extension
        print("🔧 Enabling pgvector extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
        # Create all tables
        print("📦 Creating tables...")
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    print("✅ Database initialized successfully!")


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
