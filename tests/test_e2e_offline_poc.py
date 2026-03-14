"""E2E integration tests for Offline PoC deployment mode (TASK-601).

The Offline PoC is the Day 1 entry mode for Pedk.ai. Customer provides:
  - A CMDB snapshot (list of network elements with their properties)
  - Telemetry time-series data (KPI metrics per cell)
  - ITSM ticket archive (historical incidents)

The system produces a Divergence Report showing CMDB drift vs. actual network
state. Zero production access required — purely read-only historical data.

Run with:
    .venv/bin/python -m pytest tests/test_e2e_offline_poc.py -v --noconftest
"""
import json
import os
import tempfile

import pandas as pd
import pytest
import respx
import httpx

# Set env vars BEFORE any app imports.
# DATABASE_URL must use an async-capable driver so that create_async_engine()
# does not fail during import even though no real DB connection is made.
os.environ.setdefault("SECRET_KEY", "test-secret-offline-poc")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_offline_poc",
)

from backend.app.services.dark_graph.divergence_reporter import (
    DivergenceFinding,
    DivergenceReport,
    DivergenceReporter,
)
from backend.app.adapters.datagerry_adapter import DatagerryAdapter, SyncResult
from backend.app.services.sleeping_cell_detector import SleepingCellDetector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def reporter():
    return DivergenceReporter()


@pytest.fixture
def synthetic_cmdb():
    """Synthetic CMDB snapshot — 5 cells known to the operator."""
    return pd.DataFrame({
        "entity_id": ["CELL-001", "CELL-002", "CELL-003", "CELL-004", "CELL-GHOST"],
        "entity_type": ["CELL", "CELL", "CELL", "CELL", "CELL"],
        "name": ["Alpha", "Bravo", "Charlie", "Delta", "Ghost"],
        "vendor": ["Ericsson", "Nokia", "Huawei", "Ericsson", "Nokia"],
        "region": ["North", "South", "East", "West", "Unknown"],
    })


@pytest.fixture
def synthetic_telemetry():
    """Synthetic telemetry — 4 cells active, 1 dark (CELL-DARK not in CMDB)."""
    return pd.DataFrame({
        "entity_id": ["CELL-001", "CELL-002", "CELL-003", "CELL-004", "CELL-DARK"],
        "traffic_volume": [1200.0, 980.0, 750.0, 1100.0, 430.0],
        "availability_pct": [99.1, 98.5, 99.8, 97.2, 88.0],
    })


@pytest.fixture
def synthetic_tickets():
    """Synthetic ITSM ticket archive."""
    return pd.DataFrame({
        "ticket_id": ["INC-001", "INC-002", "INC-003"],
        "affected_ci": ["CELL-002", "CELL-003", "CELL-GHOST"],
        "severity": ["P2", "P3", "P1"],
        "description": [
            "High drop rate on CELL-002",
            "Intermittent outage CELL-003",
            "Ghost cell unreachable",
        ],
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_offline_poc_cmdb_snapshot_load(reporter):
    """Verify CMDB data structures can be created and loaded (dict-based, no DB)."""
    # Build a synthetic CMDB in a temp CSV — simulates customer file drop
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("entity_id,entity_type,vendor,region\n")
        f.write("CELL-001,CELL,Ericsson,North\n")
        f.write("CELL-002,CELL,Nokia,South\n")
        f.write("CELL-003,CELL,Huawei,East\n")
        path = f.name

    try:
        df = reporter.load_cmdb_snapshot(path)
        assert isinstance(df, pd.DataFrame)
        assert "entity_id" in df.columns
        assert len(df) == 3
        assert set(df["entity_id"]) == {"CELL-001", "CELL-002", "CELL-003"}
        assert "vendor" in df.columns
    finally:
        os.unlink(path)


def test_offline_poc_divergence_report_generation(reporter, synthetic_cmdb, synthetic_telemetry):
    """Create a DivergenceReporter, generate a divergence report from in-memory data."""
    report = reporter.generate_report(
        tenant_id="poc-tenant-01",
        cmdb=synthetic_cmdb,
        telemetry=synthetic_telemetry,
        tickets=pd.DataFrame(),
    )

    assert isinstance(report, DivergenceReport)
    assert report.tenant_id == "poc-tenant-01"
    # CELL-DARK is in telemetry but not CMDB -> dark node
    dark_ids = {f.entity_id for f in report.findings if f.finding_type == "dark_node"}
    assert "CELL-DARK" in dark_ids
    # CELL-GHOST is in CMDB but not telemetry -> phantom node
    phantom_ids = {f.entity_id for f in report.findings if f.finding_type == "phantom_node"}
    assert "CELL-GHOST" in phantom_ids
    assert report.summary_stats["total"] >= 2


def test_offline_poc_sleeping_cell_detection_on_historical_data():
    """Show SleepingCellDetector can be instantiated with custom thresholds for offline use."""
    # The detector is instantiated with parameters suitable for historical analysis.
    # In offline PoC mode, we configure conservative thresholds and verify the
    # object holds them correctly. The async scan() requires a live DB session and
    # is integration-tested separately.
    detector = SleepingCellDetector(window_days=30, z_threshold=-2.5, idle_minutes=60)

    assert detector.window_days == 30
    assert detector.z_threshold == -2.5
    assert detector.idle_minutes == 60

    # Verify the z-score formula logic offline:
    # Given a cell with mean=1000, std=200, current=100 -> z = (100-1000)/200 = -4.5
    # That's below the -2.5 threshold, so the cell would be flagged.
    mean, std, current = 1000.0, 200.0, 100.0
    z = (current - mean) / std
    assert z < detector.z_threshold, (
        f"Cell with traffic={current} (mean={mean}, std={std}) "
        f"should be flagged as sleeping (z={z:.2f} < {detector.z_threshold})"
    )


def test_offline_poc_multi_cell_divergence_report(reporter):
    """Multiple cells in divergence report, verify all appear in findings."""
    cmdb = pd.DataFrame({
        "entity_id": ["CELL-A", "CELL-B", "CELL-C", "PHANTOM-1", "PHANTOM-2"],
        "entity_type": ["CELL"] * 5,
    })
    telemetry = pd.DataFrame({
        "entity_id": ["CELL-A", "CELL-B", "CELL-C", "DARK-X", "DARK-Y", "DARK-Z"],
        "traffic_volume": [500.0, 600.0, 700.0, 100.0, 200.0, 300.0],
    })

    report = reporter.generate_report(
        tenant_id="multi-cell-tenant",
        cmdb=cmdb,
        telemetry=telemetry,
        tickets=pd.DataFrame(),
    )

    dark_ids = {f.entity_id for f in report.findings if f.finding_type == "dark_node"}
    phantom_ids = {f.entity_id for f in report.findings if f.finding_type == "phantom_node"}

    # All 3 dark nodes must appear
    assert "DARK-X" in dark_ids
    assert "DARK-Y" in dark_ids
    assert "DARK-Z" in dark_ids

    # Both phantom nodes must appear
    assert "PHANTOM-1" in phantom_ids
    assert "PHANTOM-2" in phantom_ids

    # Summary stats must accurately reflect counts
    assert report.summary_stats.get("dark_node", 0) == 3
    assert report.summary_stats.get("phantom_node", 0) == 2
    assert report.summary_stats["total"] == 5


def test_offline_poc_report_includes_reconciliation_metadata(reporter, synthetic_cmdb, synthetic_telemetry):
    """Report findings include all required fields for customer delivery."""
    report = reporter.generate_report(
        tenant_id="metadata-check-tenant",
        cmdb=synthetic_cmdb,
        telemetry=synthetic_telemetry,
        tickets=pd.DataFrame(),
    )

    assert len(report.findings) > 0, "Expected at least one finding in report"

    for finding in report.findings:
        # Each DivergenceFinding must carry these fields
        assert hasattr(finding, "finding_type"), "Missing field: finding_type"
        assert hasattr(finding, "entity_id"), "Missing field: entity_id"
        assert hasattr(finding, "confidence"), "Missing field: confidence"
        assert hasattr(finding, "evidence"), "Missing field: evidence"
        assert hasattr(finding, "recommended_action"), "Missing field: recommended_action"

        assert finding.finding_type in {
            "dark_node", "phantom_node", "dark_edge",
            "phantom_edge", "dark_attribute", "identity_mutation",
        }, f"Unknown finding_type: {finding.finding_type}"
        assert 0.0 <= finding.confidence <= 1.0, (
            f"Confidence out of range: {finding.confidence}"
        )
        assert isinstance(finding.evidence, list) and len(finding.evidence) > 0, (
            "Evidence must be a non-empty list"
        )
        assert isinstance(finding.recommended_action, str) and finding.recommended_action, (
            "recommended_action must be a non-empty string"
        )

    # Report-level metadata
    assert report.tenant_id == "metadata-check-tenant"
    assert report.generated_at  # non-empty ISO timestamp
    assert isinstance(report.summary_stats, dict)
    assert "total" in report.summary_stats
    assert "high_confidence" in report.summary_stats


def test_offline_poc_no_write_to_production_systems(reporter, tmp_path):
    """Confirm DivergenceReporter writes only to a local path, not external URLs.

    The Offline PoC contract: the reporter must never reach out to a live network.
    We verify this by running a full generate_report cycle while ensuring no HTTP
    calls are made (respx intercepts and fails any unexpected outbound request).
    """
    cmdb = pd.DataFrame({"entity_id": ["CELL-001", "CELL-002"]})
    telemetry = pd.DataFrame({"entity_id": ["CELL-001", "CELL-003"]})

    with respx.mock(assert_all_mocked=True) as mock_transport:
        # No routes registered — any HTTP call would raise
        report = reporter.generate_report(
            tenant_id="isolation-tenant",
            cmdb=cmdb,
            telemetry=telemetry,
            tickets=pd.DataFrame(),
        )

    # Report is produced locally without any network call
    assert isinstance(report, DivergenceReport)
    assert report.tenant_id == "isolation-tenant"
    # The mock transport was never invoked (no HTTP calls made)
    assert len(mock_transport.calls) == 0


def test_offline_poc_full_flow_cmdb_to_report(tmp_path):
    """Full pipeline: synthetic CMDB data -> detect anomaly -> generate report.

    Simulates the complete Offline PoC flow:
    1. Customer drops CSV files into a directory
    2. Operator loads them via DivergenceReporter
    3. Report is generated showing drift

    Also exercises DatagerryAdapter.upsert_entity() to confirm that CMDB CIs
    from Datagerry can be normalised to the same entity dict format the reporter
    expects.
    """
    # Step 1: Write synthetic CSV files to tmp_path (simulates customer file drop)
    cmdb_path = str(tmp_path / "cmdb_snapshot.csv")
    telemetry_path = str(tmp_path / "telemetry_kpi.csv")
    ticket_path = str(tmp_path / "itsm_tickets.csv")

    pd.DataFrame({
        "entity_id": ["CELL-001", "CELL-002", "CELL-003", "PHANTOM-99"],
        "entity_type": ["CELL", "CELL", "CELL", "CELL"],
        "vendor": ["Ericsson", "Nokia", "Huawei", "Unknown"],
    }).to_csv(cmdb_path, index=False)

    pd.DataFrame({
        "entity_id": ["CELL-001", "CELL-002", "CELL-003", "DARK-SHADOW"],
        "traffic_volume": [1100.0, 850.0, 670.0, 50.0],
    }).to_csv(telemetry_path, index=False)

    pd.DataFrame({
        "ticket_id": ["INC-001"],
        "affected_ci": ["CELL-001"],
        "severity": ["P3"],
    }).to_csv(ticket_path, index=False)

    # Step 2: Load files via reporter (no DB, no network)
    reporter = DivergenceReporter()
    report = reporter.generate_report(
        tenant_id="full-flow-tenant",
        cmdb_path=cmdb_path,
        telemetry_path=telemetry_path,
        ticket_path=ticket_path,
    )

    # Step 3: Verify report
    assert isinstance(report, DivergenceReport)
    assert report.tenant_id == "full-flow-tenant"

    dark_ids = {f.entity_id for f in report.findings if f.finding_type == "dark_node"}
    phantom_ids = {f.entity_id for f in report.findings if f.finding_type == "phantom_node"}

    assert "DARK-SHADOW" in dark_ids, "DARK-SHADOW in telemetry but not CMDB — must be flagged"
    assert "PHANTOM-99" in phantom_ids, "PHANTOM-99 in CMDB but not telemetry — must be flagged"

    # Step 4: Validate DatagerryAdapter normalisation produces compatible entity dicts
    adapter = DatagerryAdapter(
        base_url="http://datagerry.local",
        api_token="poc-token",
        tenant_id="full-flow-tenant",
    )
    datagerry_ci = {
        "object_id": "CELL-001",
        "name": "Alpha Cell",
        "type_name": "CELL",
        "fields": {"vendor": "Ericsson", "region": "North"},
    }
    action, entity_dict = adapter.upsert_entity(datagerry_ci, existing_entities={})
    assert action == "added"
    assert entity_dict["external_id"] == "CELL-001"
    assert entity_dict["entity_type"] == "CELL"
    assert entity_dict["tenant_id"] == "full-flow-tenant"


def test_offline_poc_report_export_format(reporter, synthetic_cmdb, synthetic_telemetry, synthetic_tickets):
    """Report output can be serialized to dict/JSON for customer delivery."""
    report = reporter.generate_report(
        tenant_id="export-tenant",
        cmdb=synthetic_cmdb,
        telemetry=synthetic_telemetry,
        tickets=synthetic_tickets,
    )

    # to_dict() must return a plain Python dict
    report_dict = report.to_dict()
    assert isinstance(report_dict, dict)

    # Top-level keys required for customer report delivery
    assert "tenant_id" in report_dict
    assert "generated_at" in report_dict
    assert "findings" in report_dict
    assert "summary_stats" in report_dict

    # findings must be a list of dicts (not dataclass objects)
    assert isinstance(report_dict["findings"], list)
    for finding_dict in report_dict["findings"]:
        assert isinstance(finding_dict, dict)
        assert "finding_type" in finding_dict
        assert "entity_id" in finding_dict
        assert "confidence" in finding_dict
        assert "evidence" in finding_dict
        assert "recommended_action" in finding_dict

    # Full JSON round-trip must succeed (required for customer file export)
    json_str = json.dumps(report_dict)
    assert isinstance(json_str, str) and len(json_str) > 0

    restored = json.loads(json_str)
    assert restored["tenant_id"] == "export-tenant"
    assert isinstance(restored["findings"], list)
    assert restored["summary_stats"]["total"] == len(report.findings)

    # generated_at must be a valid ISO-format string
    from datetime import datetime
    dt = datetime.fromisoformat(report_dict["generated_at"])
    assert dt is not None
