import pytest
from uuid import uuid4
from sqlalchemy import text
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.cx_intelligence import CXIntelligenceService

@pytest.mark.asyncio
async def test_cx_graph_traversal(db_session):
    """
    Verifies that CX Intelligence correctly traverses the topology graph.
    Finding H-3 Verification.
    """
    service = CXIntelligenceService(db_session)
    
    # 1. Setup Topology (Root -> Router -> Cell)
    root_id = "CORE-ROUTER-99"
    router_id = "AGG-ROUTER-55"
    cell_id = "CELL-105"
    
    # Create relationships ensuring required fields are present
    rel1 = EntityRelationshipORM(
        from_entity_id=root_id,
        to_entity_id=router_id,
        from_entity_type="router",
        to_entity_type="router",
        relationship_type="connects_to"
    )
    rel2 = EntityRelationshipORM(
        from_entity_id=router_id,
        to_entity_id=cell_id,
        from_entity_type="router",
        to_entity_type="cell",
        relationship_type="serves"
    )
    db_session.add_all([rel1, rel2])
    
    # 2. Seed Customer on the downstream Cell
    cust_id = uuid4()
    customer = CustomerORM(
        id=cust_id,
        external_id="CUST-999-DOWNSTREAM", # Required unique field
        name="Downstream Victim",
        associated_site_id=cell_id, # Linked to the leaf node
        churn_risk_score=0.95 # High risk
    )
    db_session.add(customer)
    
    # 3. Create Anomaly on the Root Node
    trace = DecisionTraceORM(
        id=uuid4(),
        tenant_id="test",
        trigger_type="alarm",
        trigger_description="Core Router Failure",
        decision_summary="Rerouted",
        tradeoff_rationale="N/A",
        action_taken="none",
        decision_maker="AI",
        context={"site_id": root_id} # The anomaly is at the top
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 4. Run Impact Analysis (Default threshold 0.7, customer has 0.95 -> FOUND)
    impacted = await service.identify_impacted_customers(trace.id)
    assert len(impacted) == 1
    
    # 5. TEST GOVERNANCE: Raise churn threshold to 0.99
    from backend.app.services.policy_engine import policy_engine
    policy_engine.parameters["cx_churn_risk_alert_threshold"] = 0.99
    
    # Re-run: 0.95 risk is now BELOW 0.99 threshold. Should find nothing.
    impacted_none = await service.identify_impacted_customers(trace.id)
    print(f"Impacted with 0.99 threshold: {len(impacted_none)}")
    assert len(impacted_none) == 0
    
    # Cleanup: Reset threshold
    policy_engine.parameters["cx_churn_risk_alert_threshold"] = 0.70

async def test_cx_entity_inference(db_session):
    """Finding H-9: Verify inference of site_id from affected_entities if missing."""
    import uuid
    service = CXIntelligenceService(db_session)
    
    # 1. Create Topology: Parent (Site-ABC) -> Child (Cell-99)
    from backend.app.models.topology_models import EntityRelationshipORM
    rel = EntityRelationshipORM(
        from_entity_id="Site-ABC", from_entity_type="site",
        relationship_type="connected_to",
        to_entity_id="Cell-99", to_entity_type="cell"
    )
    db_session.add(rel)
    
    # 2. Create Customer at Cell-99
    cust = CustomerORM(
        id=uuid.uuid4(), name="Inference User", 
        associated_site_id="Cell-99", churn_risk_score=0.9,
        external_id="C-INF"
    )
    db_session.add(cust)
    
    # 3. Create Anomaly with NO site_id but with affected_entities=['Cell-99']
    trace = DecisionTraceORM(
        tenant_id="test", trigger_type="anomaly", 
        trigger_description="Amorphous cluster fault",
        decision_summary="Test inference anomaly",
        tradeoff_rationale="Simulated inference testing",
        action_taken="NO_ACTION",
        decision_maker="pedkai:test_suite",
        context={"affected_entities": ["Cell-99"]} # No site_id!
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 4. Run Impact Analysis
    # It should: 
    # a) See missing site_id
    # b) Infer site_id='Site-ABC' from 'Cell-99'
    # c) Find downstream 'Cell-99'
    # d) Find the customer
    impacted = await service.identify_impacted_customers(trace.id)
    
    assert len(impacted) == 1
    assert impacted[0].associated_site_id == "Cell-99"
    print("Successfully inferred site_id from child entity!")
