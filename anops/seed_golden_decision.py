"""
Script to seed multiple 'Golden Decisions' for different ANOps scenarios.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.embedding_service import get_embedding_service

async def seed_golden_decisions():
    """Seeds a variety of high-confidence successful decisions."""
    print("🌟 Seeding Golden Decisions...")
    
    tenant_id = "global-demo"
    embedding_service = get_embedding_service()
    
    decisions = [
        {
            "trigger": "Significant throughput drop (80%) detected on 5G Cell sector.",
            "summary": "Resolved throughput degradation via remote tilt adjustment and PRB rebalancing.",
            "rationale": "Remote tilt adjustment preferred over site dispatch to minimize MTTR. Inter-cell interference was confirmed via neighbor cell metrics.",
            "action": "Applied +2 degree RET (Remote Electrical Tilt) and scheduler PRB weighting update.",
            "domain": "anops"
        },
        {
            "trigger": "High congestion (95%+ PRB utilization) with latency spikes >100ms.",
            "summary": "Mitigated congestion by activating Dynamic Spectrum Sharing (DSS) and offloading non-critical traffic.",
            "rationale": "DSS allows 5G/4G spectrum elasticity. Offloading non-critical traffic preserves the Gold SLA for Finance customers.",
            "action": "Activated DSS on Cell Sector and applied QoS traffic steering policy to offload background syncs to 4G.",
            "domain": "anops"
        },
        {
            "trigger": "Sleeping Cell detected: Active users dropped to 0 while site status is UP.",
            "summary": "Restored sleeping cell via automated software reset of the Baseband Unit (BBU).",
            "rationale": "Software lock-up suspected post-patch. Remote reset is the fastest recovery path before dispatching field tech.",
            "action": "Executed remote BBU cold-restart sequence and verified user attachment recovery.",
            "domain": "anops"
        },
        {
            "trigger": "VoLTE Call Drop Rate (CDR) spike to 15% on IMS core gateway.",
            "summary": "Mitigated Voice drops by re-routing signaling traffic to standby IMS node.",
            "rationale": "Primary IMS TAS node showed high CPU utilization. Re-routing preserves 99.9% voice reliability target.",
            "action": "Updated IMS S-CSCF routing policy to drain traffic from affected TAS and failover to standby-node-02.",
            "domain": "anops"
        },
        {
            "trigger": "SMS delivery latency spiked to 65s on SMSC-LON-001.",
            "summary": "Resolved SMS delivery delays by flushing transient queue and increasing SMPP link capacity.",
            "rationale": "Queue backlog detected due to marketing broadcast. Priority traffic was being throttled. Flushing non-critical transient queue restored delivery speed.",
            "action": "Executed SMSC queue flush for low-priority shortcodes and increased concurrent SMPP sessions by 50%.",
            "domain": "anops"
        },
        {
            "trigger": "Emergency dial-out blockage (25% failure rate) at Central Exchange.",
            "summary": "Restored emergency call priority by triggering Circuit-Switched Fallback (CSFB) and overrides.",
            "rationale": "Exchange congestion was blocking all call types. SLA for emergency services requires 100% priority. Activated override to drop low-priority voice circuits for 999/911.",
            "action": "Triggered Exchange Priority Override for emergency prefixes and forced CSFB for non-essential traffic.",
            "domain": "anops"
        }
    ]
    
    async with get_db_context() as session:
        for d in decisions:
            trace = DecisionTraceORM(
                tenant_id=tenant_id,
                trigger_type="alarm",
                trigger_description=d["trigger"],
                decision_summary=d["summary"],
                tradeoff_rationale=d["rationale"],
                action_taken=d["action"],
                decision_maker="system:expert-v1",
                confidence_score=0.98,
                domain=d["domain"],
                context={"affected_entities": ["cell-generic"]},
                outcome={
                    "status": "success",
                    "resolution_time_minutes": 10,
                    "customer_impact_count": 0,
                    "sla_violated": False
                }
            )
            
            # Generate embedding
            text = embedding_service.create_decision_text(
                trigger_description=d["trigger"],
                decision_summary=d["summary"],
                tradeoff_rationale=d["rationale"],
                action_taken=d["action"]
            )
            embedding = await embedding_service.generate_embedding(text)
            if embedding:
                trace.embedding = embedding
                
            session.add(trace)
            print(f"  - Seeded: {d['summary'][:40]}...")
            
        await session.commit()
        print("✅ All Golden Decisions seeded.")

if __name__ == "__main__":
    asyncio.run(seed_golden_decisions())
