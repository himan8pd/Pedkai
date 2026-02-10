"""
Unit tests for RCA Logic.
"""
import pytest
from unittest.mock import MagicMock
import json

# Assuming the logic is in backend.app.services.rca_service (or similar)
# Since we don't have a standalone service yet (it's in event_handlers),
# we will mock the graph logic or refactor later.
# For now, we'll verify the helper functions if they exist, or test the normalizer.

from data_fabric.alarm_normalizer import AlarmNormalizer

def test_alarm_normalizer_ericsson():
    """Test normalizing Ericsson XML alarm."""
    normalizer = AlarmNormalizer()
    
    raw_event = """
    <alarmEvent>
        <specificProblem>LinkFailure</specificProblem>
        <managedObjectInstance>Site-123</managedObjectInstance>
        <eventTime>2023-10-27T12:00:00Z</eventTime>
    </alarmEvent>
    """
    
    normalized = normalizer.normalize(raw_event, "ericsson")
    
    assert normalized["description"] == "LinkFailure"
    assert normalized["entity_id"] == "Site-123"
    assert normalized["event_type"] == "equipmentAlarm"

def test_alarm_normalizer_nokia():
    """Test normalizing Nokia JSON alarm."""
    normalizer = AlarmNormalizer()
    
    raw_event = json.dumps({
        "sourceIndicator": "NetAct",
        "alarmText": "HighTemp",
        "dn": "PLMN-PLMN/MRBTS-123",
        "severity": "MAJOR"
    })
    
    normalized = normalizer.normalize(raw_event, "nokia")
    
    assert normalized["description"] == "HighTemp"
    assert normalized["entity_id"] == "NetAct" # sourceIndicator is mapped to entity_id in current impl
    assert normalized["severity"] == "critical" # MAJOR maps to critical
