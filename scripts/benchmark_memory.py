"""
Pedkai Memory Benchmarking Tool.
Evaluates Decision Memory retrieval precision/recall against a Gold Standard.
"""
import asyncio
import json
import numpy as np
import time
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, Text

from backend.app.core.database import get_db_context, engine, Base
from backend.app.models.decision_trace_orm import DecisionTraceORM, DecisionFeedbackORM
from backend.app.core.config import get_settings

# --- SQLite Compliance Patches ---
@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(Vector, 'sqlite')
def compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(UUID, 'sqlite')
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from backend.app.services.embedding_service import get_embedding_service
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.models.decision_trace import SimilarDecisionQuery, DecisionContext, KPISnapshot

settings = get_settings()
embed_service = get_embedding_service()

# Gold Standard: A set of synthetic anomalies and their 'Perfect Match' content
# Finding H-1: Expanded to 25+ items with distractors to prevent tautological results
GOLD_STANDARD = [
    # Core Network Issues (5)
    {
        "id": "GS-001",
        "description": "High PRB utilization causing latency spikes on 5G Cell",
        "tags": ["congestion", "prb", "5g"],
        "target_problem": "PRB Congestion"
    },
    {
        "id": "GS-002",
        "description": "Power loss on backhaul transport node",
        "tags": ["power", "transport", "outage"],
        "target_problem": "Power Loss"
    },
    {
        "id": "GS-003",
        "description": "Sleeping cell - low active users despite high neighbor traffic",
        "tags": ["sleeping_cell", "silent_failure"],
        "target_problem": "Sleeping Cell"
    },
    {
        "id": "GS-004",
        "description": "Packet loss on S1-U interface between eNodeB and SGW",
        "tags": ["packet_loss", "s1u", "lte"],
        "target_problem": "S1-U Packet Loss"
    },
    {
        "id": "GS-005",
        "description": "MME overload causing attach failures",
        "tags": ["mme", "overload", "attach_failure"],
        "target_problem": "MME Overload"
    },
    
    # Radio Access Network Issues (8)
    {
        "id": "GS-006",
        "description": "Antenna tilt misconfiguration causing coverage hole",
        "tags": ["antenna", "coverage", "tilt"],
        "target_problem": "Coverage Hole"
    },
    {
        "id": "GS-007",
        "description": "Interference from neighboring cell on same PCI",
        "tags": ["interference", "pci", "collision"],
        "target_problem": "PCI Collision"
    },
    {
        "id": "GS-008",
        "description": "Handover failure rate spike during rush hour",
        "tags": ["handover", "mobility", "failure"],
        "target_problem": "Handover Failure"
    },
    {
        "id": "GS-009",
        "description": "RACH preamble collision causing random access delays",
        "tags": ["rach", "preamble", "collision"],
        "target_problem": "RACH Collision"
    },
    {
        "id": "GS-010",
        "description": "Uplink noise floor increase due to external interference",
        "tags": ["uplink", "noise", "interference"],
        "target_problem": "Uplink Interference"
    },
    {
        "id": "GS-011",
        "description": "CQI reporting degradation affecting throughput",
        "tags": ["cqi", "throughput", "degradation"],
        "target_problem": "CQI Degradation"
    },
    {
        "id": "GS-012",
        "description": "MIMO rank adaptation failure reducing spectral efficiency",
        "tags": ["mimo", "rank", "efficiency"],
        "target_problem": "MIMO Failure"
    },
    {
        "id": "GS-013",
        "description": "Carrier aggregation deactivation causing capacity loss",
        "tags": ["carrier_aggregation", "capacity", "5g"],
        "target_problem": "CA Deactivation"
    },
    
    # Transport & Backhaul Issues (5)
    {
        "id": "GS-014",
        "description": "Fiber cut on primary backhaul link",
        "tags": ["fiber", "backhaul", "outage"],
        "target_problem": "Fiber Cut"
    },
    {
        "id": "GS-015",
        "description": "Microwave link degradation during heavy rain",
        "tags": ["microwave", "weather", "degradation"],
        "target_problem": "Microwave Fade"
    },
    {
        "id": "GS-016",
        "description": "MPLS LSP flapping causing jitter",
        "tags": ["mpls", "lsp", "jitter"],
        "target_problem": "MPLS Instability"
    },
    {
        "id": "GS-017",
        "description": "QoS policy misconfiguration dropping VoLTE packets",
        "tags": ["qos", "volte", "packet_drop"],
        "target_problem": "QoS Misconfiguration"
    },
    {
        "id": "GS-018",
        "description": "BGP route flap affecting core routing",
        "tags": ["bgp", "routing", "flap"],
        "target_problem": "BGP Flap"
    },
    
    # Customer Experience Issues (4)
    {
        "id": "GS-019",
        "description": "Video streaming buffering for premium customers",
        "tags": ["video", "buffering", "customer"],
        "target_problem": "Video Buffering"
    },
    {
        "id": "GS-020",
        "description": "VoLTE call drop rate exceeding SLA threshold",
        "tags": ["volte", "call_drop", "sla"],
        "target_problem": "VoLTE Call Drop"
    },
    {
        "id": "GS-021",
        "description": "IoT device connection timeout in smart city deployment",
        "tags": ["iot", "timeout", "smart_city"],
        "target_problem": "IoT Timeout"
    },
    {
        "id": "GS-022",
        "description": "Enterprise VPN throughput degradation",
        "tags": ["vpn", "enterprise", "throughput"],
        "target_problem": "VPN Degradation"
    },
    
    # BSS/OSS Issues (3)
    {
        "id": "GS-023",
        "description": "Billing system delay causing revenue leakage",
        "tags": ["billing", "revenue", "delay"],
        "target_problem": "Billing Delay"
    },
    {
        "id": "GS-024",
        "description": "Provisioning system timeout preventing new activations",
        "tags": ["provisioning", "timeout", "activation"],
        "target_problem": "Provisioning Timeout"
    },
    {
        "id": "GS-025",
        "description": "CRM sync failure causing customer data inconsistency",
        "tags": ["crm", "sync", "data"],
        "target_problem": "CRM Sync Failure"
    },
    
    # Distractors (3) - Unrelated issues to test precision
    {
        "id": "DISTRACTOR-001",
        "description": "Office WiFi router firmware update scheduled",
        "tags": ["wifi", "firmware", "office"],
        "target_problem": "WiFi Maintenance"
    },
    {
        "id": "DISTRACTOR-002",
        "description": "Data center cooling system maintenance",
        "tags": ["datacenter", "cooling", "maintenance"],
        "target_problem": "Cooling Maintenance"
    },
    {
        "id": "DISTRACTOR-003",
        "description": "Employee laptop security patch deployment",
        "tags": ["laptop", "security", "patch"],
        "target_problem": "Security Patch"
    }
]

async def seed_data(session):
    """Seed the database with real embeddings for benchmark traces."""
    print("🌱 Seeding benchmark data with real embeddings...")
    traces = []
    for item in GOLD_STANDARD:
        # Generate real embedding
        text = embed_service.create_decision_text(
            trigger_description=item["description"],
            decision_summary=f"Resolved {item['target_problem']}",
            tradeoff_rationale="Balanced performance vs cost",
            action_taken="Optimized parameters"
        )
        vector = await embed_service.generate_embedding(text)
        
        trace = DecisionTraceORM(
            tenant_id="default",
            trigger_type="anomaly",
            trigger_description=item["description"],
            decision_summary=f"Resolved {item['target_problem']}",
            tradeoff_rationale="Balanced performance vs cost",
            action_taken="Optimized parameters",
            decision_maker="AI",
            tags=item["tags"],
            domain="anops",
            context={"problem": item["target_problem"]},
            embedding=vector
        )
        traces.append(trace)
    
    session.add_all(traces)
    await session.commit()
    print(f"✅ Seeded {len(traces)} traces with embeddings.")

def cosine_similarity(v1, v2):
    if v1 is None or v2 is None: return 0.0
    v1 = np.array(v1)
    v2 = np.array(v2)
    return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

# Finding H-1 FIX: Paraphrased queries to test semantic similarity, not keyword matching
PARAPHRASED_QUERIES = {
    "GS-001": "5G cell experiencing latency due to full PRB",
    "GS-002": "Backhaul node went down due to power failure",
    "GS-003": "Cell showing no traffic despite neighbors being busy",
    "GS-004": "SGW link showing packet drops",
    "GS-005": "Signaling storm overwheming the MME",
    "GS-006": "Coverage gap caused by bad antenna tilt",
    "GS-007": "PCI conflict with neighbor cell",
    "GS-008": "High mobility failure rate during peak hours",
    "GS-009": "Random access failures due to excessive collisions",
    "GS-010": "Interference raising the uplink noise floor",
    "GS-011": "User throughput dropping due to poor channel reporting",
    "GS-012": "Spectral efficiency loss from MIMO config",
    "GS-013": "5G capacity drop from Carrier Aggregation failure",
    "GS-014": "Primary transport link fiber break",
    "GS-015": "Rain fade affecting microwave backhaul",
    "GS-016": "Jitter caused by MPLS route instability",
    "GS-017": "VoLTE quality issues due to wrong QoS headers",
    "GS-018": "Core router BGP session flapping",
    "GS-019": "VIP users complaining about video stalls",
    "GS-020": "Voice calls dropping more than allowed by SLA",
    "GS-021": "Smart city sensors timing out",
    "GS-022": "Corporate VPN connection slowness",
    "GS-023": "Revenue risk from billing latency",
    "GS-024": "New SIMs not activating due to timeout",
    "GS-025": "Customer profiles out of sync between CRM and Network",
    "DISTRACTOR-001": "WiFi firmware upgrade in the office",
    "DISTRACTOR-002": "AC maintenance in server room",
    "DISTRACTOR-003": "Deploying security patches to workstations"
}

async def run_benchmark():
    print("🚀 Starting Pedkai Memory Optimization Benchmark (Real Math)...")
    
    # 1. Initialize Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    thresholds = [0.5, 0.6, 0.7, 0.8, 0.9]
    results = {}

    async with get_db_context() as session:
        # 2. Seed if necessary
        count_query = select(DecisionTraceORM).limit(1)
        res = await session.execute(count_query)
        if not res.first():
            await seed_data(session)

        # Fetch all traces for local cosine similarity check (fallback for SQLite)
        all_traces_query = select(DecisionTraceORM)
        res = await session.execute(all_traces_query)
        all_traces = res.scalars().all()

        for threshold in thresholds:
            print(f"Testing threshold: {threshold}...")
            start_time = time.time()
            
            total_precision = 0
            total_recall = 0
            
            for test_case in GOLD_STANDARD:
                # Use Paraphrased query to test REAL semantic search
                query_text = embed_service.create_decision_text(
                    trigger_description=PARAPHRASED_QUERIES.get(test_case["id"], test_case["description"]),
                    decision_summary="",
                    tradeoff_rationale="",
                    action_taken=""
                )
                query_vector = await embed_service.generate_embedding(query_text)
                
                # Perform search
                hits = []
                # Finding M-8 FIX: Production-grade PGVector search
                if engine.dialect.name == "postgresql":
                    # Use pgvector's native distance operators
                    from pgvector.sqlalchemy import Vector
                    res = await session.execute(
                        select(DecisionTraceORM)
                        .where(DecisionTraceORM.embedding.cosine_distance(query_vector) <= (1 - threshold))
                        .order_by(DecisionTraceORM.embedding.cosine_distance(query_vector))
                    )
                    hits = res.scalars().all()
                else:
                    # Fallback for local SQLite development
                    for trace in all_traces:
                        sim = cosine_similarity(query_vector, trace.embedding)
                        if sim >= threshold:
                            hits.append(trace)
                
                # In this small set, recall=1 if we find the exact match
                found_match = any(h.trigger_description == test_case["description"] for h in hits)
                
                total_precision += (1.0 if len(hits) == 1 and found_match else (1.0/len(hits) if len(hits) > 0 else 0))
                total_recall += (1.0 if found_match else 0)

            avg_precision = total_precision / len(GOLD_STANDARD)
            avg_recall = total_recall / len(GOLD_STANDARD)
            latency = (time.time() - start_time) * 1000 / len(GOLD_STANDARD)
            
            results[threshold] = {
                "precision": round(avg_precision, 2),
                "recall": round(avg_recall, 2),
                "latency_ms": round(latency, 2)
            }

    print("\n--- BENCHMARK RESULTS (REAL MATH) ---")
    print(f"{'Threshold':<12} | {'Precision':<10} | {'Recall':<10} | {'Latency (ms)':<12}")
    print("-" * 55)
    for t, data in results.items():
        print(f"{t:<12} | {data['precision']:<10} | {data['recall']:<10} | {data['latency_ms']:<12}")
    
    # Find optimal (highest precision + recall)
    optimal = max(results.keys(), key=lambda t: results[t]["precision"] + results[t]["recall"])
    print(f"\n✅ Optimization recommendation: {optimal} satisfies precision/recall balance.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
