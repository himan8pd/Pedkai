import pytest
from backend.app.services.netconf_adapter import NetconfSession

def test_netconf_mock_connect():
    s = NetconfSession(host="nokia-mock-host")
    ok = s.connect(use_mock=True)
    assert ok
    assert s.vendor == "nokia"

def test_netconf_validate_and_execute():
    s = NetconfSession(host="nokia-mock-host")
    s.connect(use_mock=True)
    v = s.validate("cell_failover", {"target_cell": "cell-2"})
    assert v.get("valid") is True
    r = s.execute("cell_failover", {"target_cell": "cell-2"})
    assert r.get("success") is True
