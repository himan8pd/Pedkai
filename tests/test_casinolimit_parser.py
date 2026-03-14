"""Tests for CasinoLimitParser (TASK-303)."""
import csv
import json
import tempfile
import os
import pytest
from datetime import datetime, timezone
from backend.app.adapters.casinolimit_parser import (
    CasinoLimitParser, CMDBSnapshot, UnifiedSignal, EnrichedSignal
)

@pytest.fixture
def parser():
    return CasinoLimitParser()

@pytest.fixture
def flows_csv(tmp_path):
    f = tmp_path / "flows.csv"
    f.write_text("src_ip,dst_ip,src_port,dst_port,protocol,bytes,packets,timestamp\n"
                 "10.0.0.1,192.168.1.1,443,12345,TCP,1024,10,1703123456\n"
                 "MALFORMED_ROW\n"  # should be skipped
                 "10.0.0.2,192.168.1.2,80,54321,TCP,512,5,1703123500\n")
    return str(f)

@pytest.fixture
def syscalls_csv(tmp_path):
    f = tmp_path / "syscalls.csv"
    f.write_text("process_id,syscall_name,args,return_code,timestamp,host_id\n"
                 "1234,open,/etc/passwd,0,1703123456,host-001\n"
                 "5678,connect,'127.0.0.1 80',0,1703123500,host-002\n")
    return str(f)

@pytest.fixture
def mitre_csv(tmp_path):
    f = tmp_path / "mitre.csv"
    f.write_text("timestamp,host_id,technique_id,tactic,confidence\n"
                 "1703123456,host-001,T1055,privilege-escalation,0.9\n"
                 "1703123500,host-002,T1190,initial-access,0.7\n")
    return str(f)

def test_parse_network_flows_returns_signals(parser, flows_csv):
    signals = parser.parse_network_flows(flows_csv)
    assert len(signals) >= 2
    assert all(s.signal_type == "network_flow" for s in signals)

def test_unknown_ip_is_dark(parser, flows_csv):
    signals = parser.parse_network_flows(flows_csv)
    assert all(s.is_dark for s in signals)  # No CMDB enrichment yet

def test_malformed_records_skipped(parser, flows_csv):
    # Should not raise, and should skip malformed rows
    signals = parser.parse_network_flows(flows_csv)
    assert len(signals) >= 1  # at least the valid rows

def test_parse_syscalls_host_id_as_entity(parser, syscalls_csv):
    signals = parser.parse_syscalls(syscalls_csv)
    assert len(signals) == 2
    assert signals[0].payload["host_id"] == "host-001"
    assert signals[0].entity_id == "host-001"

def test_parse_mitre_labels(parser, mitre_csv):
    signals = parser.parse_mitre_labels(mitre_csv)
    assert len(signals) == 2
    assert signals[0].payload["technique_id"] == "T1055"
    assert signals[0].signal_type == "mitre_label"

def test_enrich_resolves_ip_to_entity(parser, flows_csv):
    cmdb = CMDBSnapshot(
        ip_to_entity={"10.0.0.1": "entity-alpha"},
        host_to_entity={}
    )
    signals = parser.parse_network_flows(flows_csv)
    enriched = parser.enrich_with_cmdb(signals, cmdb)
    alpha_signals = [e for e in enriched if e.signal.entity_id == "entity-alpha"]
    assert len(alpha_signals) >= 1
    assert not alpha_signals[0].signal.is_dark

def test_mitre_labels_produce_intrusion_candidate(parser, mitre_csv):
    signals = parser.parse_mitre_labels(mitre_csv)
    cmdb = CMDBSnapshot()
    enriched = parser.enrich_with_cmdb(signals, cmdb)
    intrusion_findings = [
        f for e in enriched for f in e.divergence_findings
        if f.get("type") == "INTRUSION_CANDIDATE"
    ]
    assert len(intrusion_findings) == 2  # 100% of MITRE labels
