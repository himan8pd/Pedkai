"""
Bulk Embedding Backfill Script.
Queries decision traces without embeddings and populates them.
"""
import asyncio
import argparse
from typing import List
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.embedding_service import get_embedding_service
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

async def backfill_embeddings(batch_size: int = 50, dry_run: bool = False):
    """Backfill missing embeddings for decision traces."""
    embedding_service = get_embedding_service()
    
    async with async_session_maker() as session:
        # Find records with missing embeddings
        stmt = select(DecisionTraceORM).where(DecisionTraceORM.embedding.is_(None))
        result = await session.execute(stmt)
        records = result.scalars().all()
        
        total = len(records)
        if total == 0:
            logger.info("No records found missing embeddings.")
            return

        logger.info(f"Found {total} records missing embeddings. Starting backfill (batch_size={batch_size}, dry_run={dry_run})...")
        
        count = 0
        for i in range(0, total, batch_size):
            batch = records[i:i+batch_size]
            
            for record in batch:
                # Prepare text for embedding
                text = embedding_service.create_decision_text(
                    trigger_description=record.trigger_description or "",
                    decision_summary=record.decision_summary or "",
                    tradeoff_rationale=record.tradeoff_rationale or "",
                    action_taken=record.action_taken or ""
                )
                
                if not dry_run:
                    embedding = await embedding_service.generate_embedding(text)
                    if embedding:
                        record.embedding = embedding
                        record.embedding_provider = embedding_service.provider
                        record.embedding_model = embedding_service.model_name
                        count += 1
                else:
                    count += 1
            
            if not dry_run:
                await session.commit()
                logger.info(f"Committed batch {i//batch_size + 1}. Total processed: {min(i+batch_size, total)}/{total}")
            else:
                logger.info(f"Dry run: Would have processed batch {i//batch_size + 1}. Total: {min(i+batch_size, total)}/{total}")

        logger.info(f"Backfill complete. Processed {count} records.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missing embeddings.")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for processing.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without committing changes.")
    args = parser.parse_args()
    
    asyncio.run(backfill_embeddings(batch_size=args.batch_size, dry_run=args.dry_run))
