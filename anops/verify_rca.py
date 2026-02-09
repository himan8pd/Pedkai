"""
Verification script for Root Cause Analysis (RCA).
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from anops.root_cause_analysis import RootCauseAnalyzer

async def verify_rca(target_external_id: str = "CELL_LON_001"):
    """
    Verifies that RCA can find upstream and downstream entities.
    """
    print(f"🔍 Running RCA Verification for {target_external_id}...")
    
    tenant_id = "global-demo"
    
    async with get_db_context() as session:
        analyzer = RootCauseAnalyzer(session)
        
        result = await analyzer.analyze_incident(target_external_id, tenant_id)
        
        if "error" in result:
            print(f"❌ Error: {result['error']}")
            return

        print(f"\n📊 Incident Context for {result['entity_name']} ({result['entity_type']}):")
        
        print("\n🛠️  Upstream Dependencies (Potential Root Causes):")
        for u in result["upstream_dependencies"]:
            print(f"  - {u['entity_type']} {u['entity_name']} ({u['relationship']})")
            
        print("\n📉 Downstream Impacts (Affected Customers):")
        for d in result["downstream_impacts"]:
            print(f"  - {d['entity_type']} {d['entity_name']} ({d['relationship']})")
            
        print("\n🚨 Critical SLA Breaches:")
        for s in result["critical_slas"]:
            print(f"  - {s['entity_type']} {s['entity_name']} ({s['relationship']})")

        # Basic validation
        has_upstream = len(result["upstream_dependencies"]) > 0
        has_downstream = len(result["downstream_impacts"]) > 0
        
        if has_upstream and has_downstream:
            print("\n✅ RCA Verification SUCCESS: Found both root cause path and impact path.")
        else:
            print("\n❌ RCA Verification FAILED: Missing either upstream or downstream context.")

if __name__ == "__main__":
    asyncio.run(verify_rca())
