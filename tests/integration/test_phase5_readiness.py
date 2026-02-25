import pytest
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models.incident_orm import IncidentORM
from backend.app.models.audit_orm import IncidentAuditEntryORM
from backend.app.models.action_execution_orm import ActionExecutionORM, ActionState
from backend.app.models.kpi_sample_orm import KpiSampleORM
from backend.app.schemas.incidents import IncidentStatus, IncidentSeverity
from backend.app.services.autonomous_action_executor import AutonomousActionExecutor

@pytest.mark.asyncio
async def test_incident_audit_trail_integrity(client: AsyncClient, db_session: AsyncSession):
    """R-16: Verify persistent audit trail logging across incident lifecycle."""
    # 1. Create Incident
    payload = {
        "tenant_id": "test-tenant",
        "title": "High Latency in Cell-A1",
        "severity": "major",
        "entity_id": "cell-a1"
    }
    resp = await client.post("/api/v1/incidents/", json=payload)
    assert resp.status_code == 201
    incident_id = resp.json()["id"]

    # 2. Check Audit Table
    stmt = select(IncidentAuditEntryORM).where(IncidentAuditEntryORM.incident_id == incident_id)
    result = await db_session.execute(stmt)
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].action == "ANOMALY_DETECTED"
    assert entries[0].action_type == "automated"
    assert entries[0].actor == "pedkai-platform"

    # 1.5 Generate SITREP (Internal Transition)
    resp = await client.post(f"/api/v1/incidents/{incident_id}/generate-sitrep")
    assert resp.status_code == 200

    # 3. Advance to SITREP Approved (Human Gate 1)
    approval_payload = {"approved_by": "engineer@pedkai.ai", "reason": "Confirmed RCA"}
    resp = await client.post(f"/api/v1/incidents/{incident_id}/approve-sitrep", json=approval_payload)
    assert resp.status_code == 200

    # 4. Verify persistent audit log for human action
    result = await db_session.execute(stmt.order_by(IncidentAuditEntryORM.timestamp.asc()))
    entries = result.scalars().all()
    assert len(entries) == 3
    assert entries[2].action == "SITREP_APPROVED"
    assert entries[2].action_type == "human"
    assert entries[2].actor == "engineer@pedkai.ai"

@pytest.mark.asyncio
async def test_audit_trail_csv_export(client: AsyncClient, db_session: AsyncSession):
    """R-16: Verify CSV export contains action_type and trace_id."""
    # Create incident with some history
    incident = IncidentORM(
        id=str(uuid4()),
        tenant_id="test-tenant",
        title="CSV Test Incident",
        severity="minor",
        status="closed",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(incident)
    
    audit_entry = IncidentAuditEntryORM(
        incident_id=incident.id,
        tenant_id="test-tenant",
        action="TEST_ACTION",
        action_type="rl_system",
        actor="rl_unit_test",
        details="CSV Validation",
        trace_id="trace-csv-123"
    )
    db_session.add(audit_entry)
    await db_session.commit()

    resp = await client.get(f"/api/v1/incidents/{incident.id}/audit-trail/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    
    content = resp.text
    assert "action_type" in content
    assert "trace_id" in content
    assert "rl_system" in content
    assert "trace-csv-123" in content

@pytest.mark.asyncio
async def test_digital_twin_similarity_integration(db_session: AsyncSession):
    """R-14: Verify Digital Twin uses embeddings for similarity lookup."""
    from backend.app.services.digital_twin import DigitalTwinMock
    
    # Mock LLM Adapter
    mock_adapter = AsyncMock()
    mock_adapter.embed.return_value = [0.1] * 3072
    
    with patch("backend.app.services.digital_twin.get_adapter", return_value=mock_adapter):
        dt = DigitalTwinMock(None)
        # We don't need real traces if it falls back to heuristic on empty DB,
        # but we want to see it CALLING the embed method.
        await dt.predict(db_session, "cell_failover", "cell-1", {"p": 1})
        
        mock_adapter.embed.assert_called_once()
        # Verify it embedded the context string
        args, _ = mock_adapter.embed.call_args
        assert "cell_failover" in args[0]
        assert "cell-1" in args[0]

@pytest.mark.asyncio
async def test_safety_gates_blast_radius(db_session: AsyncSession, session_factory):
    """R-9: Verify Blast Radius gate blocks oversized actions."""
    executor = AutonomousActionExecutor(session_factory)
    
    # Submit action with affected_entity_count > 10
    action = await executor.submit_action(
        db_session, "test-tenant", "failover", "node-1", affected_entity_count=15
    )
    # Ensure it's in DB
    await db_session.commit()
    
    # Mock the queue to return only one item and then stop
    with patch("backend.app.services.autonomous_action_executor._pending_queue.get", side_effect=[action.id, asyncio.CancelledError()]):
        try:
            await executor._worker_loop()
        except asyncio.CancelledError:
            pass
        
    # Re-fetch from DB using a fresh session to check state
    async with session_factory() as session:
         stmt = select(ActionExecutionORM).where(ActionExecutionORM.id == action.id)
         res = await session.execute(stmt)
         updated_action = res.scalar_one()
         assert updated_action.state == ActionState.FAILED
         assert updated_action.result["reason"] == "blast_radius_exceeded"

@pytest.mark.asyncio
async def test_safety_gates_validation_rollback(db_session: AsyncSession, session_factory):
    """R-8: Verify post-execution validation triggers auto-rollback on degradation."""
    executor = AutonomousActionExecutor(session_factory)
    
    # Setup action.entity_id as a STRING representation of UUID
    eid = uuid4()
    eid_str = str(eid)
    
    # 1. Setup Action
    action_id = str(uuid4())
    action = ActionExecutionORM(
        id=action_id,
        tenant_id="test-tenant",
        action_type="cell_failover",
        entity_id=eid_str,
        affected_entity_count=1,
        state=ActionState.PENDING
    )
    db_session.add(action)
    
    # 2. Setup KPI Baseline (Traffic = 100)
    for i in range(5):
        sample = KpiSampleORM(
            tenant_id="test-tenant",
            entity_id=eid, # Column expects UUID object
            metric_name="traffic_volume",
            value=100.0,
            timestamp=datetime.now(timezone.utc),
            source="SYNTHETIC_TEST"
        )
        db_session.add(sample)
    await db_session.commit()

    # 3. Execution Simulation
    # We mock _worker_loop internals to skip gates and jump to validation
    # Or just test _validate_post_execution directly
    from backend.app.services.digital_twin import Prediction
    pred = Prediction(risk_score=10, impact_delta=0.01, confidence_interval="0-0")
    
    # Pre-degradation check
    passed = await executor._validate_post_execution(db_session, action, pred)
    # Wait, it will poll. Let's mock the sleep to be fast.
    with patch("asyncio.sleep", return_value=None):
        # Now add DEGRADED KPIs (Traffic = 80, which is > 10% drop from 100)
        for i in range(5):
             db_session.add(KpiSampleORM(
                tenant_id="test-tenant",
                entity_id=eid,
                metric_name="traffic_volume",
                value=85.0, # 15% drop
                timestamp=datetime.now(timezone.utc),
                source="SYNTHETIC_TEST"
            ))
        await db_session.commit()
        
        passed = await executor._validate_post_execution(db_session, action, pred)
        assert passed is False # Should fail validation
