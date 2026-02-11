"""
Sets up the database tables for Pedkai benchmarking.
"""
import asyncio
from backend.app.core.database import engine, Base
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

from backend.app.models.decision_trace_orm import DecisionTraceORM, DecisionFeedbackORM

async def setup_db():
    print("🔧 Initializing database tables...")
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tables created successfully.")

if __name__ == "__main__":
    asyncio.run(setup_db())
