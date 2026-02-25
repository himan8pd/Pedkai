import pytest
import uuid
from datetime import datetime, timezone
from httpx import AsyncClient
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.core.security import create_access_token, Role

@pytest.mark.asyncio
async def test_alarm_correlation_endpoint(client: AsyncClient, db_session):
    """Verify Finding 5: Real grouping logic instead of 'batch of 5' demo logic."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN, "tenant_id": "t1"})
    headers = {"Authorization": f"Bearer {token}"}
    
    now = datetime.now(timezone.utc)
    
    # Insert decision traces that SHOULD be clustered (same entity)
    for i in range(3):
        trace = DecisionTraceORM(
            id=uuid.uuid4(),
            title=f"Alarm {i}",
            trigger_description=f"Alarm {i}",
            severity="major",
            ack_state="unacknowledged",
            entity_id="site-x",
            entity_type="NODE",
            tenant_id="t1",
            trigger_type="alarm",
            decision_summary="sum",
            tradeoff_rationale="rat",
            action_taken="act",
            decision_maker="autobot",
            domain="anops",
            decision_made_at=now,
            created_at=now
        )
        db_session.add(trace)
    
    # Insert one more on different entity
    trace_y = DecisionTraceORM(
        id=uuid.uuid4(),
        title="Diff Alarm",
        trigger_description="Diff Alarm",
        severity="minor",
        ack_state="unacknowledged",
        entity_id="site-y",
        entity_type="NODE",
        tenant_id="t1",
        trigger_type="alarm",
        decision_summary="sum",
        tradeoff_rationale="rat",
        action_taken="act",
        decision_maker="autobot",
        domain="anops",
        decision_made_at=now,
        created_at=now
    )
    db_session.add(trace_y)
    await db_session.commit()
    
    resp = await client.get("/api/v1/service-impact/clusters", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    
    # Should see 2 clusters: site-x (3 alarms) and site-y (1 alarm)
    assert len(data) == 2
    
    # Check site-x cluster details
    x_cluster = next(c for c in data if c["root_cause_entity_id"] == "site-x")
    assert x_cluster["alarm_count"] == 3
    assert x_cluster["noise_reduction_pct"] == round((2/3)*100, 1)
