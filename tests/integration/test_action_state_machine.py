import pytest
from backend.app.models.action_execution_orm import ActionExecutionORM, ActionState

def test_action_state_enum():
    assert ActionState.PENDING.value == "pending"
    assert ActionState.COMPLETED.value == "completed"
