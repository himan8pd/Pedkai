import pytest
import uuid
from sqlalchemy import text
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.cx_intelligence import CXIntelligenceService

@pytest.mark.asyncio
async def test_cx_graph_traversal(db_session):
    """
    Verifies that CX Intelligence correctly traverses the topology graph.
    """
    service = CXIntelligenceService(db_session)
    
    # 1. Setup Topology (Root -> Router -> Cell)
    root_id = "CORE-ROUTER-99"
    router_id = "AGG-ROUTER-55"
    cell_id = "CELL-105"
    
    rel1 = EntityRelationshipORM(
        from_entity_id=root_id,
        to_entity_id=router_id,
        from_entity_type="router",
        to_entity_type="router",
        relationship_type="connects_to",
        tenant_id="default"
    )
    rel2 = EntityRelationshipORM(
        from_entity_id=router_id,
        to_entity_id=cell_id,
        from_entity_type="router",
        to_entity_type="cell",
        relationship_type="serves",
        tenant_id="default"
    )
    db_session.add_all([rel1, rel2])
    
    # 2. Seed Customer
    cust_id = uuid.uuid4()
    customer = CustomerORM(
        id=cust_id,
        external_id="CUST-999-DOWNSTREAM",
        name="Downstream Victim",
        associated_site_id=cell_id,
        churn_risk_score=0.95,
        tenant_id="default"
    )
    db_session.add(customer)
    
    # 3. Create Anomaly
    trace = DecisionTraceORM(
        id=uuid.uuid4(),
        tenant_id="default",
        trigger_type="alarm",
        trigger_description="Core Router Failure",
        decision_summary="Rerouted",
        tradeoff_rationale="N/A",
        action_taken="none",
        decision_maker="AI",
        context={"site_id": root_id}
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 4. Run Impact Analysis
    impacted = await service.identify_impacted_customers(trace.id)
    assert len(impacted) == 1


@pytest.mark.asyncio
async def test_cx_entity_inference(db_session):
    """Verify inference of site_id from affected_entities if missing."""
    service = CXIntelligenceService(db_session)
    
    # 1. Create Topology
    rel = EntityRelationshipORM(
        from_entity_id="Site-ABC", from_entity_type="site",
        relationship_type="connected_to",
        to_entity_id="Cell-99", to_entity_type="cell",
        tenant_id="default"
    )
    db_session.add(rel)
    
    # 2. Create Customer
    cust = CustomerORM(
        id=uuid.uuid4(), name="Inference User", 
        associated_site_id="Cell-99", churn_risk_score=0.9,
        external_id="C-INF",
        tenant_id="default"
    )
    db_session.add(cust)
    
    # 3. Create Anomaly with NO site_id
    trace = DecisionTraceORM(
        id=uuid.uuid4(),
        tenant_id="default", trigger_type="anomaly", 
        trigger_description="Amorphous cluster fault",
        decision_summary="Test inference anomaly",
        tradeoff_rationale="Simulated inference testing",
        action_taken="NO_ACTION",
        decision_maker="pedkai:test_suite",
        context={"affected_entities": ["Cell-99"]}
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 4. Run Impact Analysis
    impacted = await service.identify_impacted_customers(trace.id)
    assert len(impacted) == 1
    assert impacted[0].associated_site_id == "Cell-99"
