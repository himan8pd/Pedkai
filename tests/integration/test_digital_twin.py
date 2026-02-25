import pytest
from backend.app.services.digital_twin import DigitalTwinMock

@pytest.mark.asyncio
async def test_digital_twin_fallback():
    dt = DigitalTwinMock()
    pred = await dt.predict(None, action_type="cell_failover", entity_id="cell-1", parameters=None)
    assert hasattr(pred, "risk_score")
    assert hasattr(pred, "impact_delta")

@pytest.mark.asyncio
async def test_digital_twin_with_fake_session(monkeypatch):
    class FakeTrace:
        def __init__(self):
            self.created_at = None
            self.impact_delta = 0.05
            self.outcome_success = True
    class FakeSession:
        async def execute(self, stmt):
            class Res:
                def scalars(self):
                    class ScalarsResult:
                        def all(self):
                            return [FakeTrace(), FakeTrace(), FakeTrace()]
                    return ScalarsResult()
            return Res()
    dt = DigitalTwinMock()
    pred = await dt.predict(FakeSession(), action_type="cell_failover", entity_id="cell-1")
    assert isinstance(pred.impact_delta, float)
