import pytest
from backend.app.services.causal_models import CausalModelLibrary, CausalTemplate

def test_causal_matching_power_failure():
    # Mock templates to avoid file IO during basic unit test
    lib = CausalModelLibrary()
    lib.templates = [
        CausalTemplate(
            id="power_failure",
            description="Mains power failure at site triggering BBU offline",
            cause_metric="mains_power",
            effect_metric="bbu_status",
            entity_type_pair=["SITE", "BBU"],
            confidence=0.98
        )
    ]
    
    anomalies = [
        {"entity_id": "site-1", "entity_type": "SITE", "metric_name": "mains_power", "value": 0},
        {"entity_id": "bbu-1", "entity_type": "BBU", "metric_name": "bbu_status", "value": 0}
    ]
    
    matches = lib.match_causal_templates(anomalies)
    assert len(matches) == 1
    assert matches[0]["template_id"] == "power_failure"
    assert "site-1" in matches[0]["evidence"]["causes"]
    assert "bbu-1" in matches[0]["evidence"]["effects"]

def test_causal_matching_no_match():
    lib = CausalModelLibrary()
    lib.templates = [
        CausalTemplate(
            id="fiber_cut",
            description="Fiber cut",
            cause_metric="fiber_status",
            effect_metric="gnodeb_connectivity",
            entity_type_pair=["FIBER", "GNODEB"],
            confidence=0.95
        )
    ]
    
    anomalies = [
        {"entity_id": "site-1", "entity_type": "SITE", "metric_name": "mains_power", "value": 0}
    ]
    
    matches = lib.match_causal_templates(anomalies)
    assert len(matches) == 0

def test_causal_matching_partial_match():
    lib = CausalModelLibrary()
    lib.templates = [
        CausalTemplate(
            id="prb_utilization",
            description="Congestion",
            cause_metric="prb_utilization",
            effect_metric="dl_throughput",
            entity_type_pair=["CELL", "CELL"],
            confidence=0.9
        )
    ]
    
    # Only cause, no effect
    anomalies = [
        {"entity_id": "cell-1", "entity_type": "CELL", "metric_name": "prb_utilization", "value": 0.95}
    ]
    
    matches = lib.match_causal_templates(anomalies)
    assert len(matches) == 0
