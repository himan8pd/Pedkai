"""
Multi-scenario verification of the ANOps Intelligence Layer.
Tests Throughput Drop, Congestion, and Sleeping Cell scenarios.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from anops.root_cause_analysis import RootCauseAnalyzer
from backend.app.services.llm_service import get_llm_service
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.embedding_service import get_embedding_service
from backend.app.models.decision_trace import SimilarDecisionQuery, DecisionContext

async def verify_scenario(target_external_id: str, query_text: str):
    """
    Executes the full reasoning loop for a specific scenario.
    """
    print(f"\n🚀 >>> STARTING SITREP GENERATION FOR: {target_external_id} ({query_text.split(':')[0]})")
    
    tenant_id = "global-demo"
    # Ensure environment model is set
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    
    async with get_db_context() as session:
        # 1. Root Cause Analysis
        print("🔍 1. Running RCA...")
        analyzer = RootCauseAnalyzer(session)
        rca_context = await analyzer.analyze_incident(target_external_id, tenant_id)
        
        # 2. Decision Memory Lookup
        print("🧠 2. Searching Decision Memory...")
        repo = DecisionTraceRepository(session)
        embedding_service = get_embedding_service()
        
        query_embedding = await embedding_service.generate_embedding(query_text)
        
        similar_decisions = []
        if query_embedding:
            mock_query = SimilarDecisionQuery(
                tenant_id=tenant_id,
                current_context=DecisionContext(trigger_description=query_text),
                limit=1,
                min_similarity=0.0
            )
            results = await repo.find_similar(mock_query, query_embedding)
            similar_decisions = [trace for trace, score in results]
            print(f"   Found {len(similar_decisions)} similar past decisions.")
        
        # 3. LLM Explanation
        print("🤖 3. Generating LLM SITREP...")
        llm_service = get_llm_service()
        sitrep = await llm_service.generate_explanation(rca_context, similar_decisions)
        
        print("\n" + "="*60)
        print(f"ANOPs SITREP: {target_external_id}")
        print("="*60)
        print(sitrep)
        print("="*60)

async def main():
    scenarios = [
        ("CELL_LON_001", "Significant throughput drop detected on sector."),
        ("CELL_LON_002", "High congestion and PRB utilization with latency spikes."),
        ("CELL_LON_003", "Sleeping Cell: Active users dropped to zero while site is UP."),
        ("IMS_001", "VoLTE Call Drop Rate (CDR) spike detected on core gateway."),
        ("SMSC_001", "SMS delivery latency spiked on primary center."),
        ("EXCH_001", "Emergency dial-out blockage detected at Central Exchange.")
    ]
    
    for eid, query in scenarios:
        await verify_scenario(eid, query)

if __name__ == "__main__":
    asyncio.run(main())
