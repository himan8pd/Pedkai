import pytest
import asyncio
from backend.app.services.digital_twin import DigitalTwinMock
from backend.app.services.netconf_adapter import NetconfSession

@pytest.mark.asyncio
async def test_autonomous_e2e_dry_run():
    # Seed: 5 cells simulation (simplified)
    dt = DigitalTwinMock()
    pred = await dt.predict(None, action_type="cell_failover", entity_id="cell-1", parameters={"target_cell": "cell-2"})
    assert hasattr(pred, "risk_score")

    # Netconf dry-run
    s = NetconfSession(host="nokia-mock-host")
    assert s.connect(use_mock=True)
    v = s.validate("cell_failover", {"target_cell": "cell-2"})
    assert v.get("valid") is True

    # Simulate executor flow (lightweight)
    # We do not spin up full app; ensure components integrate
    from backend.app.services.autonomous_action_executor import AutonomousActionExecutor
    from backend.app.models.action_execution_orm import ActionExecutionORM
    from backend.app.core.database import async_session_maker

    executor = AutonomousActionExecutor(async_session_maker)
    await executor.start()
    # Enqueue a dry-run action (we will not check DB commit here)
    # Note: In CI, DB session fixtures would be used; here we just test no exceptions
    
    # Mock session for this test
    class FakeSession:
        def add(self, obj):
            pass
        async def flush(self):
            pass
        async def commit(self):
            pass
    
    try:
        # Use a fake session for quick smoke test of enqueue path
        action = await executor.submit_action(session=FakeSession(), tenant_id="tenant-test", action_type="cell_failover", entity_id="cell-1", affected_entity_count=3, parameters={"target_cell":"cell-2","device_host":"nokia-mock-host"}, submitted_by="tester")
        assert action.id is not None
    finally:
        await executor.stop()
