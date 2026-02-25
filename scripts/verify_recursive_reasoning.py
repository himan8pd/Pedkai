"""
Verification Script for Phase 15.3: Semantic Context Graph (Recursive Reasoning)

This script validates:
1. Recursive CTE traversal of decision chains.
2. Linkage of decisions via parent_id and derivation_type.
3. LLM synthesis of the "Lineage of Success".
"""

import asyncio
import os
import sys
from uuid import uuid4

# Ensure path includes project root
project_root = "/Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My Drive/AI Learning/AntiGravity/Pedkai"
sys.path.append(project_root)

# Load environment variables (mimicking fix_env.py)
from scripts.fix_env import load_env_manual
load_env_manual()

from sqlalchemy import select, text
from backend.app.core.database import get_db_context, engine, Base, async_session_maker
from backend.app.models.decision_trace import (
    DecisionTraceCreate,
    DecisionContext,
    DecisionOutcomeRecord,
    DecisionOutcome,
    SimilarDecisionQuery
)
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.llm_service import get_llm_service
from backend.app.services.embedding_service import get_embedding_service

async def verify_recursive_reasoning():
    print("--- Phase 15.3 Verification: Semantic Context Graph ---")
    
    # 1. Update Schema (Add all missing columns)
    print("\n1. Ensuring Schema is up to date...")
    expected_columns = {
        "parent_id": "UUID",
        "derivation_type": "VARCHAR(50)",
        "ack_state": "VARCHAR(50) DEFAULT 'unacknowledged'",
        "external_correlation_id": "VARCHAR(255)",
        "internal_correlation_id": "VARCHAR(255)",
        "probable_cause": "VARCHAR(100)",
        "feedback_score": "INTEGER DEFAULT 0",
        "domain": "VARCHAR(50) DEFAULT 'anops'"
    }
    
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='decision_traces';"))
        existing_columns = [r[0] for r in res.all()]
        
        for col, col_type in expected_columns.items():
            if col not in existing_columns:
                print(f"Adding missing column: {col} ({col_type})...")
                await conn.execute(text(f"ALTER TABLE decision_traces ADD COLUMN {col} {col_type};"))
        
        await conn.run_sync(Base.metadata.create_all)

    async with get_db_context() as session:
        repo = DecisionTraceRepository(async_session_maker)
        emb_service = get_embedding_service()
        
        # 2. Seed a Reasoning Chain
        print("\n2. Seeding Reasoning Chain (Attempt A -> Attempt B)...")
        tenant = "test-tenant-recursive"
        
        # Decision 1: Root Failure
        d1_create = DecisionTraceCreate(
            tenant_id=tenant,
            trigger_type="alarm",
            trigger_description="High PRB utilization in Cell_A",
            context=DecisionContext(affected_entities=["Cell_A"]),
            decision_summary="Increase tilt to overlap adjacent coverage",
            tradeoff_rationale="Quickest fix for congestion",
            action_taken="Increased e-tilt by 3 degrees",
            decision_maker="pedkai:system",
            domain="anops"
        )
        d1 = await repo.create(d1_create)
        
        # Mark D1 as Failure
        from backend.app.models.decision_trace import DecisionTraceUpdate
        await repo.update(d1.id, DecisionTraceUpdate(
            outcome=DecisionOutcomeRecord(
                status=DecisionOutcome.FAILURE,
                learnings="Tilt change did not relieve PRB; caused interference overshoot."
            )
        ))
        
        # Decision 2: Successful Follow-up
        d2_create = DecisionTraceCreate(
            tenant_id=tenant,
            trigger_type="follow_up",
            trigger_description="High PRB persisted after tilt change",
            context=DecisionContext(affected_entities=["Cell_A"]),
            decision_summary="Enable Second Carrier (Slice Activation)",
            tradeoff_rationale="Requires more power but adds physical capacity",
            action_taken="Activated SCell_002",
            decision_maker="pedkai:system",
            domain="anops",
            parent_id=d1.id,
            derivation_type="FOLLOW_UP"
        )
        d2 = await repo.create(d2_create)
        
        # Mark D2 as Success
        from backend.app.models.decision_trace import DecisionTraceUpdate
        await repo.update(d2.id, DecisionTraceUpdate(
            outcome=DecisionOutcomeRecord(status=DecisionOutcome.SUCCESS, learnings="Capacity relieved. 100% resolution.")
        ))
        
        # 3. Verify Recursive Retrieval
        print("\n3. Verifying Recursive Traversal...")
        chain = await repo.get_reasoning_chain(d2.id)
        print(f"Chain Length: {chain.length}")
        for i, decision in enumerate(chain.decisions):
            print(f"  [{i}] ID: {decision.id} | Action: {decision.action_taken} | Outcome: {decision.outcome.status if decision.outcome else 'N/A'}")
            
        if chain.length == 2 and chain.decisions[0].id == d1.id:
            print("✅ Recursive Reasoning Chain retrieved successfully.")
        else:
            print("❌ Chain retrieval failed!")
            return

        # 4. LLM Awareness Test
        print("\n4. Testing LLM Reasoning Chain Awareness...")
        # Create embedding for retrieval
        text_for_search = emb_service.create_decision_text(
            d1_create.trigger_description,
            d1_create.decision_summary,
            d1_create.tradeoff_rationale,
            d1_create.action_taken
        )
        embedding = await emb_service.generate_embedding(text_for_search)
        if embedding:
            await repo.set_embedding(d1.id, embedding)
            
            # Now trigger an incident that matches D1
            llm = get_llm_service()
            incident = {
                "entity_name": "CELL_LON_999",
                "entity_type": "Cell",
                "metrics": {"load": 92},
                "service_type": "DATA"
            }
            
            # Manual similarity query
            query = SimilarDecisionQuery(tenant_id=tenant, current_context=DecisionContext(), min_similarity=0.5, limit=5)
            # Find similar (should find D1)
            similar = await repo.find_similar(query, embedding)
            similar_decisions = [s[0] for s in similar]
            
            print(f"Matched {len(similar_decisions)} similar decisions. Performing SITREP generation...")
            sitrep = await llm.generate_explanation(
                incident_context=incident,
                similar_decisions=similar_decisions,
                db_session=session
            )
            
            print("\n--- SITREP OUTPUT ---")
            print(sitrep)
            print("---------------------")
            
            if "Follow-up" in sitrep or "lineage" in sitrep.lower() or "Second Carrier" in sitrep:
                print("✅ LLM effectively synthesized the reasoning chain.")
            else:
                print("⚠️ LLM SITREP did not clearly reference the chain.")
        else:
            print("⚠️ Embedding service unavailable, skipping LLM E2E test.")

if __name__ == "__main__":
    asyncio.run(verify_recursive_reasoning())
