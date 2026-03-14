"""Tests for file-based DivergenceReporter (TASK-301)."""
import json
import tempfile
import os
import pytest
import pandas as pd
from backend.app.services.dark_graph.divergence_reporter import (
    DivergenceReporter, DivergenceFinding, DivergenceReport
)


@pytest.fixture
def reporter():
    return DivergenceReporter()


def test_find_dark_nodes_basic(reporter):
    cmdb = pd.DataFrame({"entity_id": ["A", "B", "C"]})
    telemetry = pd.DataFrame({"entity_id": ["A", "B", "D"]})
    findings = reporter.find_dark_nodes(cmdb, telemetry)
    ids = {f.entity_id for f in findings}
    assert "D" in ids  # D is in telemetry but not CMDB
    assert "A" not in ids


def test_find_phantom_nodes_basic(reporter):
    cmdb = pd.DataFrame({"entity_id": ["A", "B", "GHOST"]})
    telemetry = pd.DataFrame({"entity_id": ["A", "B"]})
    findings = reporter.find_phantom_nodes(cmdb, telemetry)
    ids = {f.entity_id for f in findings}
    assert "GHOST" in ids
    assert "A" not in ids


def test_generate_report_returns_report(reporter):
    cmdb = pd.DataFrame({"entity_id": ["A", "B"]})
    telemetry = pd.DataFrame({"entity_id": ["B", "C"]})
    tickets = pd.DataFrame()
    report = reporter.generate_report("test-tenant", cmdb=cmdb, telemetry=telemetry, tickets=tickets)
    assert isinstance(report, DivergenceReport)
    assert report.tenant_id == "test-tenant"


def test_report_is_json_serialisable(reporter):
    cmdb = pd.DataFrame({"entity_id": ["X"]})
    telemetry = pd.DataFrame({"entity_id": ["Y"]})
    report = reporter.generate_report("t1", cmdb=cmdb, telemetry=telemetry, tickets=pd.DataFrame())
    d = report.to_dict()
    json.dumps(d)  # must not raise


def test_load_cmdb_from_csv(reporter):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("entity_id,entity_type\nA,CELL\nB,SITE\n")
        path = f.name
    try:
        df = reporter.load_cmdb_snapshot(path)
        assert "entity_id" in df.columns
        assert len(df) == 2
    finally:
        os.unlink(path)


def test_dark_node_finding_type(reporter):
    cmdb = pd.DataFrame({"entity_id": ["A"]})
    telemetry = pd.DataFrame({"entity_id": ["A", "DARK"]})
    findings = reporter.find_dark_nodes(cmdb, telemetry)
    assert all(f.finding_type == "dark_node" for f in findings)


def test_summary_stats_counts(reporter):
    cmdb = pd.DataFrame({"entity_id": ["A", "PHANTOM"]})
    telemetry = pd.DataFrame({"entity_id": ["A", "DARK"]})
    report = reporter.generate_report("t2", cmdb=cmdb, telemetry=telemetry, tickets=pd.DataFrame())
    assert report.summary_stats["total"] >= 2
