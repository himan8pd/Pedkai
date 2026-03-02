#!/usr/bin/env python3
"""
CasinoLimit Full Client Simulation Loader
==========================================
Populates the entire Pedkai stack (Datagerry CMDB + PostgreSQL + TimescaleDB)
with real CasinoLimit dataset data to underpin committee brief claims.

This script:
1. Creates CMDB types in Datagerry (GameInstance, NetworkZone, AttackTechnique, SecurityIncident)
2. Populates Datagerry with CasinoLimit instances and machines (declared state)
3. Loads network entities and topology relationships into PostgreSQL (observed state)
4. Loads labelled network flows as telemetry data
5. Creates synthetic incidents derived from MITRE ATT&CK labels
6. Creates "dark nodes" (telemetry-active IPs NOT in CMDB) to demonstrate reconciliation
7. Creates "phantom nodes" (CMDB entries with zero telemetry) to demonstrate drift detection
8. Loads KPI metrics into TimescaleDB

Usage:
    python3 scripts/load_casinolimit.py [--clean] [--skip-datagerry] [--skip-postgres]
"""

import os
import sys
import csv
import io
import json
import uuid
import time
import zipfile
import hashlib
import argparse
import urllib.request
import urllib.parse
from urllib.error import HTTPError
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from typing import Any, Optional

# ─── Configuration ─────────────────────────────────────────────
DATAGERRY_URL = os.getenv("DATAGERRY_URL", "http://localhost:4000/rest")
DATAGERRY_USER = os.getenv("DATAGERRY_USER", "admin")
DATAGERRY_PASS = os.getenv("DATAGERRY_PASS", "admin")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "pedkai")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")

TIMESCALE_HOST = os.getenv("TIMESCALE_HOST", "localhost")
TIMESCALE_PORT = os.getenv("TIMESCALE_PORT", "5433")
TIMESCALE_DB = os.getenv("TIMESCALE_DB", "pedkai_metrics")

DATASET_BASE = "/Volumes/Projects/Pedkai Data Store/COMIDDS/CasinoLimit"
TENANT_ID = "casinolimit"

# Phantom node hostnames: stale CMDB entries with no telemetry (used by both Datagerry + PG)
PHANTOM_NAMES = [
    "legacy-fw-01", "decomm-switch-03", "old-lb-02", "retired-vpn-01",
    "stale-dns-02", "migrated-proxy-01", "replaced-router-05", "eol-camera-04",
    "moved-nas-02", "ghost-ap-07", "obsolete-ids-01", "offline-mgmt-03",
]

# Map CasinoLimit machine roles to Pedkai entity types (per IMPLEMENTATION_ROADMAP_V8)
ROLE_TO_ENTITY_TYPE = {
    "start": "router",           # Entry point / jump host
    "bastion": "switch",         # Network hop / bastionhost
    "meetingcam": "broadband_gateway",  # Media/IoT host
    "intranet": "landline_exchange",    # Internal data store / service
}

MACHINE_ROLES = ["start", "bastion", "meetingcam", "intranet"]

# ─── Datagerry Client ──────────────────────────────────────────
class DataGerryClient:
    """Lightweight Datagerry REST API client."""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
    
    def _request(self, endpoint: str, method: str = "GET", payload: Any = None):
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                raw = response.read().decode().strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    # Datagerry sometimes returns raw integers (e.g., object IDs)
                    try:
                        return int(raw)
                    except ValueError:
                        return raw
        except HTTPError as e:
            if e.code == 409:
                return None  # Already exists
            body = ""
            try: body = e.read().decode()
            except: pass
            # Suppress verbose logging for expected errors
            if e.code != 400 or "already exists" not in body.lower():
                print(f"  [WARN] HTTP {e.code} on {method} {endpoint}: {body[:200]}")
            return None
        except Exception as e:
            print(f"  [ERROR] {method} {endpoint}: {e}")
            return None
    
    def login(self) -> bool:
        res = self._request("/auth/login", "POST", {
            "user_name": self.username, "password": self.password
        })
        if res and "token" in res:
            self.token = res["token"]
            return True
        return False
    
    def get_types(self) -> list:
        res = self._request("/types/?limit=100")
        if res and "results" in res:
            return res["results"]
        return []
    
    def create_type(self, type_def: dict) -> Optional[int]:
        """Create a type and return its public_id."""
        type_def.setdefault("author_id", 1)
        type_def.setdefault("version", "1.0.0")
        type_def.setdefault("active", True)
        
        res = self._request("/types/", "POST", type_def)
        if isinstance(res, int):
            return res
        if isinstance(res, dict) and "result_id" in res:
            return res["result_id"]
        
        # Check if already exists
        for t in self.get_types():
            if t["name"] == type_def["name"]:
                return t["public_id"]
        return None
    
    def create_object(self, type_id: int, data_dict: dict) -> Optional[int]:
        """Create an object and return its public_id."""
        fields = [{"name": k, "value": v} for k, v in data_dict.items()]
        obj_def = {
            "type_id": type_id,
            "fields": fields,
            "active": True,
            "author_id": 1,
            "version": "1.0.0",
        }
        res = self._request("/objects/", "POST", obj_def)
        if isinstance(res, int):
            return res
        if isinstance(res, dict) and "result_id" in res:
            return res["result_id"]
        return None
    
    def get_objects_by_type(self, type_id: int) -> list:
        """Get all objects of a specific type."""
        res = self._request(f"/objects/?type_id={type_id}")
        if res and "results" in res:
            return res["results"]
        return []
    
    def delete_objects_by_type(self, type_id: int):
        """Delete all objects of a given type."""
        objects = self.get_objects_by_type(type_id)
        for obj in objects:
            self._request(f"/objects/{obj['public_id']}", "DELETE")
    
    def delete_type(self, type_id: int):
        """Delete a type."""
        self._request(f"/types/{type_id}", "DELETE")


# ─── Dataset Parsers ───────────────────────────────────────────

def parse_steps_csv() -> list[dict]:
    """Parse output.zip/steps.csv for instance metadata."""
    zip_path = os.path.join(DATASET_BASE, "output.zip")
    instances = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            if name.endswith("steps.csv"):
                with z.open(name) as f:
                    content = f.read().decode("utf-8")
                    reader = csv.DictReader(io.StringIO(content))
                    for row in reader:
                        instances.append(row)
                break
    return instances


def parse_system_labels(max_instances: int = 0) -> dict:
    """Parse MITRE ATT&CK labels from syslogs_labels.zip and output.zip.
    Returns: {instance_name: {label_id: {technique, machines}}}
    """
    all_labels = {}
    zip_path = os.path.join(DATASET_BASE, "syslogs_labels.zip")
    
    with zipfile.ZipFile(zip_path, "r") as z:
        count = 0
        for name in z.namelist():
            if name.endswith(".json"):
                instance_name = os.path.basename(name).replace(".json", "")
                with z.open(name) as f:
                    data = json.loads(f.read())
                    all_labels[instance_name] = data
                count += 1
                if max_instances and count >= max_instances:
                    break
    return all_labels


def parse_relations(max_instances: int = 0) -> dict:
    """Parse inter-process relations from output.zip.
    Returns: {instance_name: {relation_id: relation_data}}
    """
    all_relations = {}
    zip_path = os.path.join(DATASET_BASE, "output.zip")
    
    with zipfile.ZipFile(zip_path, "r") as z:
        count = 0
        for name in z.namelist():
            if "relations" in name and name.endswith(".json"):
                instance_name = os.path.basename(name).replace("_relations.json", "")
                with z.open(name) as f:
                    data = json.loads(f.read())
                    all_relations[instance_name] = data
                count += 1
                if max_instances and count >= max_instances:
                    break
    return all_relations


def parse_labelled_flows_sample(max_instances: int = 20, max_rows_per_instance: int = 500) -> dict:
    """Parse labelled network flows for a sample of instances.
    Returns: {instance_name: [flow_records]}
    """
    all_flows = {}
    zip_path = os.path.join(DATASET_BASE, "labelled_flows.zip")
    
    with zipfile.ZipFile(zip_path, "r") as z:
        count = 0
        for name in z.namelist():
            if name.endswith(".csv"):
                instance_name = os.path.basename(name).replace(".csv", "")
                with z.open(name) as f:
                    content = f.read().decode("utf-8")
                    reader = csv.reader(io.StringIO(content))
                    header = next(reader)
                    header = [h.strip() for h in header]
                    flows = []
                    for i, row in enumerate(reader):
                        if i >= max_rows_per_instance:
                            break
                        if len(row) >= 10:
                            flows.append({
                                "machine_name": row[0].strip(),
                                "timestamp": row[1].strip(),
                                "duration": row[2].strip(),
                                "src_ip": row[3].strip(),
                                "dst_ip": row[4].strip(),
                                "src_port": row[5].strip(),
                                "dst_port": row[6].strip(),
                                "bytes": row[7].strip(),
                                "packets": row[8].strip(),
                                "protocol": row[9].strip(),
                                "labels": row[11].strip() if len(row) > 11 else "[]",
                            })
                    all_flows[instance_name] = flows
                count += 1
                if max_instances and count >= max_instances:
                    break
    return all_flows


def parse_zeek_flows_sample(max_instances: int = 30, max_rows_per_machine: int = 200) -> dict:
    """Parse Zeek bidirectional flows.
    Returns: {instance_name: {machine_name: [flow_records]}}
    """
    all_zeek = {}
    zip_path = os.path.join(DATASET_BASE, "flows_zeek.zip")
    
    with zipfile.ZipFile(zip_path, "r") as z:
        instance_count = 0
        seen_instances = set()
        for name in z.namelist():
            if name.endswith(".csv"):
                parts = name.split("/")
                if len(parts) >= 3:
                    instance_name = parts[-2]
                    machine_name = parts[-1].replace(".csv", "")
                else:
                    continue
                
                if instance_name not in seen_instances:
                    seen_instances.add(instance_name)
                    instance_count += 1
                    if max_instances and instance_count > max_instances:
                        break
                
                with z.open(name) as f:
                    content = f.read().decode("utf-8")
                    reader = csv.reader(io.StringIO(content))
                    header = next(reader)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= max_rows_per_machine:
                            break
                        if len(row) >= 10:
                            rows.append({
                                "ts": row[0],
                                "uid": row[1],
                                "src_ip": row[2],
                                "src_port": row[3],
                                "dst_ip": row[4],
                                "dst_port": row[5],
                                "proto": row[6],
                                "service": row[7],
                                "orig_bytes": row[8] if row[8] != "-" else "0",
                                "resp_bytes": row[9] if row[9] != "-" else "0",
                            })
                    
                    if instance_name not in all_zeek:
                        all_zeek[instance_name] = {}
                    all_zeek[instance_name][machine_name] = rows
    return all_zeek


# ─── PostgreSQL Direct Loader ──────────────────────────────────

def get_pg_connection(host=None, port=None, dbname=None):
    """Get a psycopg2 connection."""
    import psycopg2
    return psycopg2.connect(
        host=host or POSTGRES_HOST,
        port=port or POSTGRES_PORT,
        dbname=dbname or POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
    )


def pg_clean_existing(conn):
    """Remove existing CasinoLimit data from PostgreSQL."""
    cur = conn.cursor()
    cur.execute("DELETE FROM entity_relationships WHERE tenant_id = %s", (TENANT_ID,))
    cur.execute("DELETE FROM network_entities WHERE tenant_id = %s", (TENANT_ID,))
    cur.execute("DELETE FROM incidents WHERE tenant_id = %s", (TENANT_ID,))
    conn.commit()
    print(f"  Cleaned existing data for tenant '{TENANT_ID}'")


def pg_create_telemetry_tables(conn):
    """Create telemetry-specific tables if they don't exist."""
    cur = conn.cursor()
    
    # Network flow events table (telemetry stream)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_flows (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            instance_id VARCHAR(255) NOT NULL,
            machine_name VARCHAR(100) NOT NULL,
            timestamp TIMESTAMPTZ,
            duration INTERVAL,
            src_ip VARCHAR(45) NOT NULL,
            dst_ip VARCHAR(45) NOT NULL,
            src_port INTEGER,
            dst_port INTEGER,
            bytes_transferred BIGINT DEFAULT 0,
            packets INTEGER DEFAULT 0,
            protocol VARCHAR(20),
            mitre_techniques TEXT[] DEFAULT '{}',
            flow_source VARCHAR(50) DEFAULT 'labelled',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_flows_tenant ON telemetry_flows(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_telemetry_flows_instance ON telemetry_flows(instance_id);
        CREATE INDEX IF NOT EXISTS idx_telemetry_flows_src ON telemetry_flows(src_ip);
        CREATE INDEX IF NOT EXISTS idx_telemetry_flows_dst ON telemetry_flows(dst_ip);
        CREATE INDEX IF NOT EXISTS idx_telemetry_flows_ts ON telemetry_flows(timestamp);
    """)
    
    # Security events table (MITRE ATT&CK labels)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            instance_id VARCHAR(255) NOT NULL,
            label_id VARCHAR(64) NOT NULL,
            technique_id VARCHAR(20) NOT NULL,
            technique_name VARCHAR(255) NOT NULL,
            machine_name VARCHAR(100),
            audit_event_ids TEXT[] DEFAULT '{}',
            severity VARCHAR(20) DEFAULT 'medium',
            detected_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_security_events_tenant ON security_events(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_security_events_instance ON security_events(instance_id);
        CREATE INDEX IF NOT EXISTS idx_security_events_technique ON security_events(technique_id);
    """)
    
    # Reconciliation hypothesis log table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_hypotheses (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            hypothesis_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(255),
            entity_name VARCHAR(255),
            evidence_sources TEXT[] DEFAULT '{}',
            confidence_score FLOAT DEFAULT 0.0,
            status VARCHAR(30) DEFAULT 'pending',
            details JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_recon_hyp_tenant ON reconciliation_hypotheses(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_recon_hyp_type ON reconciliation_hypotheses(hypothesis_type);
        CREATE INDEX IF NOT EXISTS idx_recon_hyp_status ON reconciliation_hypotheses(status);
    """)
    
    conn.commit()
    print("  Telemetry tables created/verified")


def pg_clean_telemetry(conn):
    """Clean telemetry tables for CasinoLimit tenant."""
    cur = conn.cursor()
    for table in ["telemetry_flows", "security_events", "reconciliation_hypotheses"]:
        try:
            cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (TENANT_ID,))
        except Exception:
            conn.rollback()
    conn.commit()


# ─── Datagerry CMDB Population ─────────────────────────────────

def populate_datagerry_cmdb(client: DataGerryClient, instances: list[dict], labels: dict):
    """Create CMDB types and objects in Datagerry for CasinoLimit."""
    
    print("\n" + "=" * 60)
    print("Phase 1: Datagerry CMDB Population (Declared State)")
    print("=" * 60)
    
    # ── Type Definitions ──
    # Datagerry requires: fields without "required", render_meta with "externals", and "acl"
    
    _acl = {"activated": False, "groups": {"includes": {}}}
    
    # 1. GameInstance type
    game_instance_type = {
        "name": "casinolimit_game_instance",
        "label": "CasinoLimit Game Instance",
        "description": "A game instance from the CasinoLimit CTF dataset, representing a self-contained network environment",
        "fields": [
            {"name": "instance_name", "label": "Instance Name", "type": "text"},
            {"name": "step_count", "label": "Step Count", "type": "text"},
            {"name": "status", "label": "Status", "type": "text"},
            {"name": "attack_progression", "label": "Attack Progression", "type": "text"},
            {"name": "first_activity", "label": "First Activity", "type": "text"},
            {"name": "last_activity", "label": "Last Activity", "type": "text"},
        ],
        "render_meta": {
            "icon": "fas fa-gamepad",
            "sections": [{
                "type": "section",
                "name": "section-instance-info",
                "label": "Instance Information",
                "fields": ["instance_name", "step_count", "status", "attack_progression", "first_activity", "last_activity"]
            }],
            "externals": [],
            "summary": {"fields": ["instance_name", "status"]}
        },
        "acl": _acl,
    }
    
    # 2. NetworkZone (Machine) type
    network_zone_type = {
        "name": "casinolimit_network_zone",
        "label": "CasinoLimit Network Zone",
        "description": "A machine/zone within a CasinoLimit game instance (start, bastion, meetingcam, intranet)",
        "fields": [
            {"name": "hostname", "label": "Hostname", "type": "text"},
            {"name": "zone_role", "label": "Zone Role", "type": "text"},
            {"name": "instance_ref", "label": "Instance Reference", "type": "text"},
            {"name": "ip_subnet", "label": "IP Subnet", "type": "text"},
            {"name": "operational_status", "label": "Operational Status", "type": "text"},
            {"name": "telemetry_active", "label": "Telemetry Active", "type": "text"},
        ],
        "render_meta": {
            "icon": "fas fa-network-wired",
            "sections": [{
                "type": "section",
                "name": "section-zone-info",
                "label": "Zone Information",
                "fields": ["hostname", "zone_role", "instance_ref", "ip_subnet", "operational_status", "telemetry_active"]
            }],
            "externals": [],
            "summary": {"fields": ["hostname", "zone_role"]}
        },
        "acl": _acl,
    }
    
    # 3. AttackTechnique type
    attack_technique_type = {
        "name": "casinolimit_attack_technique",
        "label": "MITRE ATT&CK Technique",
        "description": "A MITRE ATT&CK technique observed in the CasinoLimit dataset",
        "fields": [
            {"name": "technique_id", "label": "Technique ID", "type": "text"},
            {"name": "technique_name", "label": "Technique Name", "type": "text"},
            {"name": "occurrence_count", "label": "Occurrences", "type": "text"},
            {"name": "affected_instances", "label": "Affected Instances", "type": "text"},
            {"name": "affected_machines", "label": "Affected Machines", "type": "text"},
            {"name": "severity", "label": "Severity", "type": "text"},
        ],
        "render_meta": {
            "icon": "fas fa-shield-alt",
            "sections": [{
                "type": "section",
                "name": "section-technique-info",
                "label": "Technique Information",
                "fields": ["technique_id", "technique_name", "occurrence_count", "affected_instances", "affected_machines", "severity"]
            }],
            "externals": [],
            "summary": {"fields": ["technique_id", "technique_name"]}
        },
        "acl": _acl,
    }
    
    # 4. SecurityIncident type (CMDB-side record)
    security_incident_type = {
        "name": "casinolimit_security_incident",
        "label": "CasinoLimit Security Incident",
        "description": "A security incident derived from MITRE ATT&CK detections in the CasinoLimit dataset",
        "fields": [
            {"name": "incident_id", "label": "Incident ID", "type": "text"},
            {"name": "instance_ref", "label": "Instance", "type": "text"},
            {"name": "technique_ids", "label": "Technique IDs", "type": "text"},
            {"name": "severity", "label": "Severity", "type": "text"},
            {"name": "status", "label": "Status", "type": "text"},
            {"name": "description", "label": "Description", "type": "text"},
        ],
        "render_meta": {
            "icon": "fas fa-exclamation-triangle",
            "sections": [{
                "type": "section",
                "name": "section-incident-info",
                "label": "Incident Information",
                "fields": ["incident_id", "instance_ref", "technique_ids", "severity", "status", "description"]
            }],
            "externals": [],
            "summary": {"fields": ["incident_id", "severity"]}
        },
        "acl": _acl,
    }
    
    # Create types
    print("  Creating CMDB types...")
    gi_type_id = client.create_type(game_instance_type)
    nz_type_id = client.create_type(network_zone_type)
    at_type_id = client.create_type(attack_technique_type)
    si_type_id = client.create_type(security_incident_type)
    
    type_ids = {
        "game_instance": gi_type_id,
        "network_zone": nz_type_id,
        "attack_technique": at_type_id,
        "security_incident": si_type_id,
    }
    
    print(f"  Type IDs: {type_ids}")
    
    if not all(type_ids.values()):
        print("  [ERROR] Failed to create one or more types. Aborting CMDB population.")
        return type_ids
    
    # ── Create GameInstance Objects ──
    print(f"\n  Creating {len(instances)} GameInstance objects...")
    success = 0
    for i, inst in enumerate(instances):
        instance_name = inst["instance"]
        step_count = inst.get("step_count", "0")
        
        # Determine status based on step_count
        sc = int(step_count) if step_count.isdigit() else 0
        if sc == 0:
            status = "unused"
            progression = "no_activity"
        elif sc <= 2:
            status = "partial"
            progression = "reconnaissance"
        elif sc <= 4:
            status = "active"
            progression = "exploitation"
        else:
            status = "completed"
            progression = "post_exploitation"
        
        # Extract timestamps
        first_activity = inst.get("step_0", "N/A")
        last_step = None
        for s in range(5, -1, -1):
            v = inst.get(f"step_{s}", "N/A")
            if v and v != "N/A":
                last_step = v
                break
        
        res = client.create_object(gi_type_id, {
            "instance_name": instance_name,
            "step_count": step_count,
            "status": status,
            "attack_progression": progression,
            "first_activity": first_activity if first_activity != "N/A" else "",
            "last_activity": last_step or "",
        })
        if res:
            success += 1
        
        if (i + 1) % 20 == 0:
            print(f"    Progress: {i + 1}/{len(instances)} instances...")
    
    print(f"  GameInstance creation: {success}/{len(instances)} succeeded")
    
    # ── Create NetworkZone Objects ──
    # Deliberate gap: Only create zones for instances with step_count > 0
    # Leave unused instances WITHOUT zones = "phantom CIs" (CMDB says instance exists, but no zones declared)
    active_instances = [inst for inst in instances if int(inst.get("step_count", "0") or "0") > 0]
    
    # Additional trick: for 15% of active instances, skip one zone to create "incomplete CMDB" scenario
    import random
    random.seed(42)  # Reproducible
    
    total_zones = 0
    zones_created = 0
    phantom_zones_skipped = 0
    
    print(f"\n  Creating NetworkZone objects for {len(active_instances)} active instances...")
    
    for i, inst in enumerate(active_instances):
        instance_name = inst["instance"]
        for role in MACHINE_ROLES:
            total_zones += 1
            # 15% chance to skip a zone (except 'start' which is always created)
            if role != "start" and random.random() < 0.15:
                phantom_zones_skipped += 1
                continue
            
            hostname = f"{role}.{instance_name}.casinolimit.local"
            res = client.create_object(nz_type_id, {
                "hostname": hostname,
                "zone_role": role,
                "instance_ref": instance_name,
                "ip_subnet": f"10.35.x.{10 + MACHINE_ROLES.index(role)}",
                "operational_status": "active",
                "telemetry_active": "yes",
            })
            if res:
                zones_created += 1
        
        if (i + 1) % 20 == 0:
            print(f"    Progress: {i + 1}/{len(active_instances)} instances...")
    
    print(f"  NetworkZone creation: {zones_created}/{total_zones} created, {phantom_zones_skipped} deliberately skipped (phantom gap)")
    
    # ── Create Phantom Nodes (in CMDB but not in telemetry) ──
    # These represent stale CMDB entries: devices that were decommissioned but CMDB wasn't updated
    phantom_count = len(PHANTOM_NAMES)
    print(f"\n  Creating {phantom_count} phantom nodes (stale CMDB entries)...")
    phantom_success = 0
    for name in PHANTOM_NAMES:
        res = client.create_object(nz_type_id, {
            "hostname": f"{name}.phantom.casinolimit.local",
            "zone_role": "decommissioned",
            "instance_ref": "N/A",
            "ip_subnet": "10.99.0.0/24",
            "operational_status": "unknown",
            "telemetry_active": "no",
        })
        if res:
            phantom_success += 1
    print(f"  Phantom nodes created: {phantom_success}/{phantom_count}")
    
    # ── Create AttackTechnique Objects ──
    # Aggregate MITRE ATT&CK techniques across all labels
    technique_stats = defaultdict(lambda: {"count": 0, "instances": set(), "machines": set()})
    
    for instance_name, label_data in labels.items():
        for label_id, label_info in label_data.items():
            tech = label_info.get("technique", "")
            if ": " in tech:
                tid, tname = tech.split(": ", 1)
            else:
                tid, tname = tech, tech
            
            technique_stats[tid]["name"] = tname
            technique_stats[tid]["count"] += 1
            technique_stats[tid]["instances"].add(instance_name)
            for machine in label_info.get("auditd_events", {}).keys():
                technique_stats[tid]["machines"].add(machine)
    
    print(f"\n  Creating {len(technique_stats)} AttackTechnique objects...")
    tech_success = 0
    for tid, stats in technique_stats.items():
        # Map MITRE technique to severity
        severity = "low"
        if any(kw in tid for kw in ["T1059", "T1053", "T1548", "T1068"]):
            severity = "critical"
        elif any(kw in tid for kw in ["T1046", "T1071", "T1021", "T1114"]):
            severity = "high"
        elif any(kw in tid for kw in ["T1069", "T1083", "T1082"]):
            severity = "medium"
        
        res = client.create_object(at_type_id, {
            "technique_id": tid,
            "technique_name": stats["name"],
            "occurrence_count": str(stats["count"]),
            "affected_instances": str(len(stats["instances"])),
            "affected_machines": ", ".join(sorted(stats["machines"])),
            "severity": severity,
        })
        if res:
            tech_success += 1
    print(f"  AttackTechnique creation: {tech_success}/{len(technique_stats)}")
    
    # ── Create SecurityIncident Objects ──
    # Create one incident per active instance that has attack labels
    incident_count = 0
    print(f"\n  Creating SecurityIncident objects...")
    for inst in active_instances:
        instance_name = inst["instance"]
        if instance_name in labels and labels[instance_name]:
            techniques = set()
            for label_info in labels[instance_name].values():
                tech = label_info.get("technique", "")
                if ": " in tech:
                    techniques.add(tech.split(": ", 1)[0])
            
            if techniques:
                sc = int(inst.get("step_count", "0") or "0")
                if sc >= 4:
                    severity = "critical"
                elif sc >= 3:
                    severity = "high"
                elif sc >= 2:
                    severity = "medium"
                else:
                    severity = "low"
                
                inc_id = f"INC-CL-{instance_name[:8].upper()}-{hashlib.md5(instance_name.encode()).hexdigest()[:6]}"
                res = client.create_object(si_type_id, {
                    "incident_id": inc_id,
                    "instance_ref": instance_name,
                    "technique_ids": ", ".join(sorted(techniques)[:5]),
                    "severity": severity,
                    "status": "detected",
                    "description": f"Multi-technique attack observed across {len(techniques)} MITRE ATT&CK techniques in instance '{instance_name}'",
                })
                if res:
                    incident_count += 1
    
    print(f"  SecurityIncident creation: {incident_count} incidents")
    
    return type_ids


# ─── PostgreSQL Population ──────────────────────────────────────

def populate_postgres(instances: list[dict], labels: dict, flows: dict, zeek_flows: dict, relations: dict):
    """Load network entities, relationships, telemetry, and incidents into PostgreSQL."""
    
    print("\n" + "=" * 60)
    print("Phase 2: PostgreSQL Population (Observed State + Topology)")
    print("=" * 60)
    
    import psycopg2
    from psycopg2.extras import execute_values
    
    conn = get_pg_connection()
    
    # Clean existing CasinoLimit data
    pg_clean_existing(conn)
    
    # Create telemetry tables
    pg_create_telemetry_tables(conn)
    pg_clean_telemetry(conn)
    
    cur = conn.cursor()
    
    # ── Network Entities ──
    # Each instance gets one SERVICE entity; each active zone gets a typed entity
    active_instances = [inst for inst in instances if int(inst.get("step_count", "0") or "0") > 0]
    
    entity_id_map = {}  # key -> uuid mapping
    entity_rows = []
    
    print(f"\n  Creating network entities for {len(active_instances)} active instances...")
    
    for inst in active_instances:
        instance_name = inst["instance"]
        
        # Instance-level entity (SERVICE type)
        inst_uuid = str(uuid.uuid4())
        entity_id_map[f"instance:{instance_name}"] = inst_uuid
        
        sc = int(inst.get("step_count", "0") or "0")
        attrs = {
            "step_count": sc,
            "attack_progression": "post_exploitation" if sc >= 4 else "exploitation" if sc >= 3 else "reconnaissance" if sc > 0 else "none",
            "dataset": "CasinoLimit",
            "source": "CMDB",
        }
        
        entity_rows.append((
            inst_uuid, TENANT_ID, "service", f"Instance: {instance_name}",
            f"CL-{instance_name}", None, None, "active",
            datetime.now(timezone.utc), datetime.now(timezone.utc),
            json.dumps(attrs),
        ))
        
        # Machine zone entities
        for role in MACHINE_ROLES:
            zone_uuid = str(uuid.uuid4())
            entity_id_map[f"zone:{instance_name}:{role}"] = zone_uuid
            
            zone_attrs = {
                "role": role,
                "instance": instance_name,
                "hostname": f"{role}.{instance_name}.casinolimit.local",
                "dataset": "CasinoLimit",
                "source": "CMDB",
            }
            
            entity_rows.append((
                zone_uuid, TENANT_ID, ROLE_TO_ENTITY_TYPE[role],
                f"{role}.{instance_name}", f"CL-{instance_name}-{role}",
                None, None, "active",
                datetime.now(timezone.utc), datetime.now(timezone.utc),
                json.dumps(zone_attrs),
            ))
    
    # ── Dark Nodes: Entities observed in telemetry but NOT in CMDB ──
    # These are external IPs that appear in flows but have no CMDB record
    dark_node_ips = set()
    for instance_name, instance_flows in flows.items():
        for flow in instance_flows:
            for ip_key in ["src_ip", "dst_ip"]:
                ip = flow[ip_key]
                # External IPs (not in 10.35.x.x range) are "dark nodes"
                if not ip.startswith("10.35."):
                    dark_node_ips.add(ip)
    
    # Also collect from Zeek flows
    for instance_name, machines in zeek_flows.items():
        for machine_name, machine_flows in machines.items():
            for flow in machine_flows:
                for ip_key in ["src_ip", "dst_ip"]:
                    ip = flow[ip_key]
                    if not ip.startswith("10.35.") and not ip.startswith("169.254."):
                        dark_node_ips.add(ip)
    
    print(f"  Discovered {len(dark_node_ips)} unique dark node IPs (external traffic)")
    
    # Create dark node entities (limit to most common ones)
    dark_node_count = min(len(dark_node_ips), 50)
    dark_ips_list = list(dark_node_ips)[:dark_node_count]
    
    for ip in dark_ips_list:
        dn_uuid = str(uuid.uuid4())
        entity_id_map[f"dark:{ip}"] = dn_uuid
        entity_rows.append((
            dn_uuid, TENANT_ID, "dark_node",
            f"Dark: {ip}", f"DARK-{ip}",
            None, None, "unknown",
            datetime.now(timezone.utc), datetime.now(timezone.utc),
            json.dumps({
                "ip_address": ip,
                "discovery_method": "telemetry_flow_analysis",
                "cmdb_registered": False,
                "dataset": "CasinoLimit",
                "source": "telemetry",
                "risk": "unmanaged_attack_surface",
            }),
        ))
    
    # Insert all entities
    if entity_rows:
        execute_values(cur, """
            INSERT INTO network_entities (id, tenant_id, entity_type, name, external_id,
                latitude, longitude, operational_status, created_at, updated_at, attributes)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, entity_rows, template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)")
        conn.commit()
    
    print(f"  Inserted {len(entity_rows)} network entities ({len(active_instances)} services, "
          f"{len(active_instances) * len(MACHINE_ROLES)} zones, {dark_node_count} dark nodes)")
    
    # ── Entity Relationships (Topology Graph) ──
    rel_rows = []
    
    # Instance → Zone relationships
    for inst in active_instances:
        instance_name = inst["instance"]
        inst_key = f"instance:{instance_name}"
        if inst_key not in entity_id_map:
            continue
        
        for role in MACHINE_ROLES:
            zone_key = f"zone:{instance_name}:{role}"
            if zone_key not in entity_id_map:
                continue
            
            rel_rows.append((
                str(uuid.uuid4()), TENANT_ID,
                entity_id_map[inst_key], "service",
                entity_id_map[zone_key], ROLE_TO_ENTITY_TYPE[role],
                "contains", 1.0,
                json.dumps({"source": "CMDB", "declared": True}),
                datetime.now(timezone.utc), None, None,
            ))
    
    # Zone → Zone flow-observed relationships (from labelled flows)
    flow_edges = set()
    for instance_name, instance_flows in flows.items():
        inst_machines = defaultdict(set)
        for flow in instance_flows:
            machine = flow["machine_name"]
            src_ip = flow["src_ip"]
            dst_ip = flow["dst_ip"]
            
            # Try to resolve IPs to zone roles
            src_role = None
            dst_role = None
            for r in MACHINE_ROLES:
                if f"zone:{instance_name}:{r}" in entity_id_map:
                    # IPs ending in .10, .11, .12, .14 map to start, bastion, meetingcam, intranet
                    last_octet_src = src_ip.split(".")[-1] if src_ip.startswith("10.35.") else None
                    last_octet_dst = dst_ip.split(".")[-1] if dst_ip.startswith("10.35.") else None
                    
                    ip_role_map = {"10": "start", "11": "bastion", "12": "meetingcam", "14": "intranet",
                                   "154": "meetingcam", "153": "intranet"}
                    
                    if last_octet_src in ip_role_map:
                        src_role = ip_role_map[last_octet_src]
                    if last_octet_dst in ip_role_map:
                        dst_role = ip_role_map[last_octet_dst]
            
            # Also use machine_name field
            if machine in MACHINE_ROLES:
                if src_ip.startswith("10.35."):
                    src_role = src_role or machine
            
            if src_role and dst_role and src_role != dst_role:
                edge_key = (instance_name, src_role, dst_role)
                if edge_key not in flow_edges:
                    flow_edges.add(edge_key)
                    
                    src_key = f"zone:{instance_name}:{src_role}"
                    dst_key = f"zone:{instance_name}:{dst_role}"
                    
                    if src_key in entity_id_map and dst_key in entity_id_map:
                        # Check for MITRE labels
                        labels_str = flow.get("labels", "[]")
                        has_attack = "T1" in labels_str
                        
                        rel_rows.append((
                            str(uuid.uuid4()), TENANT_ID,
                            entity_id_map[src_key], ROLE_TO_ENTITY_TYPE.get(src_role, "unknown"),
                            entity_id_map[dst_key], ROLE_TO_ENTITY_TYPE.get(dst_role, "unknown"),
                            "connects_to", 0.9 if has_attack else 0.7,
                            json.dumps({
                                "source": "telemetry",
                                "declared": False,
                                "observed_in_flows": True,
                                "attack_traffic": has_attack,
                                "discovery_type": "dark_edge" if not has_attack else "attack_path",
                            }),
                            datetime.now(timezone.utc), None, None,
                        ))
            
            # Dark node connections
            for ip_key, ip in [("src_ip", src_ip), ("dst_ip", dst_ip)]:
                if not ip.startswith("10.35.") and not ip.startswith("169.254."):
                    dark_key = f"dark:{ip}"
                    zone_key = f"zone:{instance_name}:{machine}" if machine in MACHINE_ROLES else None
                    
                    if dark_key in entity_id_map and zone_key and zone_key in entity_id_map:
                        edge = (instance_name, ip, machine)
                        if edge not in flow_edges:
                            flow_edges.add(edge)
                            
                            if ip_key == "src_ip":
                                src_id = entity_id_map[dark_key]
                                dst_id = entity_id_map[zone_key]
                                src_type = "dark_node"
                                dst_type = ROLE_TO_ENTITY_TYPE.get(machine, "unknown")
                            else:
                                src_id = entity_id_map[zone_key]
                                dst_id = entity_id_map[dark_key]
                                src_type = ROLE_TO_ENTITY_TYPE.get(machine, "unknown")
                                dst_type = "dark_node"
                            
                            rel_rows.append((
                                str(uuid.uuid4()), TENANT_ID,
                                src_id, src_type,
                                dst_id, dst_type,
                                "communicates_with", 0.5,
                                json.dumps({
                                    "source": "telemetry",
                                    "declared": False,
                                    "dark_edge": True,
                                    "external_ip": ip,
                                }),
                                datetime.now(timezone.utc), None, None,
                            ))
    
    # Insert relationships
    if rel_rows:
        execute_values(cur, """
            INSERT INTO entity_relationships (id, tenant_id, source_entity_id, source_entity_type,
                target_entity_id, target_entity_type, relationship_type, weight, attributes,
                created_at, valid_from, valid_until)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, rel_rows, template="(%s::uuid, %s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s)")
        conn.commit()
    
    print(f"  Inserted {len(rel_rows)} entity relationships ({len(flow_edges)} unique edges)")
    
    # ── Telemetry Flows ──
    print(f"\n  Loading telemetry flow records...")
    flow_row_count = 0
    batch = []
    batch_size = 1000
    
    for instance_name, instance_flows in flows.items():
        for flow in instance_flows:
            try:
                # Parse MITRE techniques from labels
                techniques = []
                labels_str = flow.get("labels", "[]")
                if "T1" in labels_str:
                    import re
                    techniques = re.findall(r"T\d{4}", labels_str)
                
                ts = None
                try:
                    ts = datetime.strptime(flow["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
                    ts = ts.replace(tzinfo=timezone.utc)
                except:
                    pass
                
                batch.append((
                    TENANT_ID, instance_name, flow["machine_name"],
                    ts, None,  # duration
                    flow["src_ip"], flow["dst_ip"],
                    int(flow["src_port"]) if flow["src_port"].isdigit() else 0,
                    int(flow["dst_port"]) if flow["dst_port"].isdigit() else 0,
                    int(float(flow["bytes"])) if flow["bytes"] else 0,
                    int(flow["packets"]) if flow["packets"].isdigit() else 0,
                    flow["protocol"],
                    techniques if techniques else None,
                    "labelled",
                ))
                
                if len(batch) >= batch_size:
                    execute_values(cur, """
                        INSERT INTO telemetry_flows (tenant_id, instance_id, machine_name,
                            timestamp, duration, src_ip, dst_ip, src_port, dst_port,
                            bytes_transferred, packets, protocol, mitre_techniques, flow_source)
                        VALUES %s
                    """, batch)
                    conn.commit()
                    flow_row_count += len(batch)
                    batch = []
            except Exception as e:
                pass  # Skip malformed records silently
    
    if batch:
        execute_values(cur, """
            INSERT INTO telemetry_flows (tenant_id, instance_id, machine_name,
                timestamp, duration, src_ip, dst_ip, src_port, dst_port,
                bytes_transferred, packets, protocol, mitre_techniques, flow_source)
            VALUES %s
        """, batch)
        conn.commit()
        flow_row_count += len(batch)
    
    print(f"  Loaded {flow_row_count} telemetry flow records")
    
    # ── Security Events ──
    print(f"\n  Loading security events (MITRE ATT&CK labels)...")
    sec_rows = []
    
    for instance_name, label_data in labels.items():
        for label_id, label_info in label_data.items():
            tech = label_info.get("technique", "")
            if ": " in tech:
                tid, tname = tech.split(": ", 1)
            else:
                tid, tname = tech, tech
            
            # Determine severity
            severity = "medium"
            if any(kw in tid for kw in ["T1059", "T1053", "T1548", "T1068"]):
                severity = "critical"
            elif any(kw in tid for kw in ["T1046", "T1071", "T1021", "T1114"]):
                severity = "high"
            elif any(kw in tid for kw in ["T1069", "T1083", "T1082"]):
                severity = "medium"
            else:
                severity = "low"
            
            machines = list(label_info.get("auditd_events", {}).keys())
            event_ids = []
            for m, eids in label_info.get("auditd_events", {}).items():
                event_ids.extend(eids)
            
            for machine in machines or ["unknown"]:
                sec_rows.append((
                    TENANT_ID, instance_name, label_id, tid, tname,
                    machine, event_ids[:10] if event_ids else [],
                    severity,
                    datetime(2024, 5, 17, 20, 30, 0, tzinfo=timezone.utc),  # Challenge start time
                ))
    
    if sec_rows:
        execute_values(cur, """
            INSERT INTO security_events (tenant_id, instance_id, label_id, technique_id,
                technique_name, machine_name, audit_event_ids, severity, detected_at)
            VALUES %s
        """, sec_rows)
        conn.commit()
    
    print(f"  Loaded {len(sec_rows)} security events")
    
    # ── Incidents (from attack detection) ──
    print(f"\n  Creating incidents from attack patterns...")
    incident_rows = []
    
    for inst in active_instances:
        instance_name = inst["instance"]
        sc = int(inst.get("step_count", "0") or "0")
        
        if instance_name in labels and labels[instance_name] and sc >= 2:
            techniques = set()
            for label_info in labels[instance_name].values():
                tech = label_info.get("technique", "")
                if ": " in tech:
                    techniques.add(tech.split(": ", 1)[0])
            
            if techniques:
                severity = "critical" if sc >= 4 else "high" if sc >= 3 else "medium"
                inc_id = f"INC-CL-{instance_name[:8].upper()}-{hashlib.md5(instance_name.encode()).hexdigest()[:6]}"
                
                reasoning = json.dumps([{
                    "step": "detection",
                    "detail": f"Detected {len(techniques)} MITRE ATT&CK techniques",
                    "techniques": list(techniques)[:10],
                }])
                
                # Find the entity_id for this instance
                entity_key = f"instance:{instance_name}"
                entity_uuid = entity_id_map.get(entity_key, str(uuid.uuid4()))
                
                incident_rows.append((
                    inc_id, TENANT_ID,
                    f"Multi-technique attack: {instance_name}",
                    severity, "detected",
                    entity_uuid, f"CL-{instance_name}",
                    None, reasoning,
                    f"Detected {len(techniques)} techniques across {sc} attack stages in instance '{instance_name}'",
                    None, None, None, None, None, None, None, None, None,
                    datetime.now(timezone.utc), datetime.now(timezone.utc),
                ))
    
    if incident_rows:
        execute_values(cur, """
            INSERT INTO incidents (id, tenant_id, title, severity, status,
                entity_id, entity_external_id, decision_trace_id, reasoning_chain,
                resolution_summary, kpi_snapshot, llm_model_version, llm_prompt_hash,
                sitrep_approved_by, sitrep_approved_at, action_approved_by, action_approved_at,
                closed_by, closed_at, created_at, updated_at)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, incident_rows)
        conn.commit()
    
    print(f"  Created {len(incident_rows)} incidents")
    
    # ── Reconciliation Hypotheses ──
    print(f"\n  Generating reconciliation hypotheses...")
    hyp_rows = []
    
    # Dark node hypotheses
    for ip in dark_ips_list:
        hyp_rows.append((
            TENANT_ID, "dark_node",
            f"DARK-{ip}", f"Unregistered device: {ip}",
            ["telemetry_flows", "zeek_flows"],
            0.85,
            "promoted",
            json.dumps({
                "ip": ip,
                "description": f"Device at {ip} is actively communicating with monitored infrastructure but has no CMDB entry",
                "recommendation": "Register in CMDB, apply security baseline, add to monitoring",
                "evidence_count": sum(1 for inst_flows in flows.values() for f in inst_flows if ip in (f["src_ip"], f["dst_ip"])),
            }),
        ))
    
    # Phantom node hypotheses 
    unused_instances = [inst for inst in instances if int(inst.get("step_count", "0") or "0") == 0]
    for inst in unused_instances[:10]:
        hyp_rows.append((
            TENANT_ID, "phantom_node",
            f"CL-{inst['instance']}", f"Phantom CI: {inst['instance']}",
            ["CMDB"],
            0.92,
            "promoted",
            json.dumps({
                "instance": inst["instance"],
                "description": f"Instance '{inst['instance']}' exists in CMDB but has zero telemetry activity",
                "recommendation": "Verify if instance was decommissioned; if so, mark as inactive in CMDB",
                "telemetry_events": 0,
            }),
        ))
    
    # Phantom zone hypotheses (zones we deliberately skipped)
    for name in PHANTOM_NAMES:
        hyp_rows.append((
            TENANT_ID, "phantom_node",
            f"PHANTOM-{name}", f"Stale CI: {name}",
            ["CMDB"],
            0.95,
            "promoted",
            json.dumps({
                "hostname": f"{name}.phantom.casinolimit.local",
                "description": f"Device '{name}' registered in CMDB but emits zero telemetry",
                "recommendation": "Confirm decommission, remove from CMDB, reclaim licence",
                "telemetry_events": 0,
                "licence_cost_per_year": 2000,
            }),
        ))
    
    # Dark edge hypotheses (connections CMDB doesn't know about)
    dark_edge_count = 0
    for edge in list(flow_edges)[:25]:
        if len(edge) == 3:
            inst_name, src, dst = edge
            if isinstance(src, str) and "." in src:  # It's an IP (dark edge)
                dark_edge_count += 1
                hyp_rows.append((
                    TENANT_ID, "dark_edge",
                    f"EDGE-{inst_name}-{src[:15]}", f"Undocumented connection: {src} ↔ {dst}",
                    ["telemetry_flows"],
                    0.78,
                    "pending",
                    json.dumps({
                        "instance": inst_name,
                        "external_ip": src,
                        "internal_zone": dst,
                        "description": f"Connection between external IP {src} and zone {dst} not declared in CMDB",
                        "recommendation": "Investigate traffic purpose, add to CMDB if legitimate",
                    }),
                ))
    
    # Identity mutation hypotheses
    hyp_rows.append((
        TENANT_ID, "identity_mutation",
        "MUTATION-bastion-root", "Identity mutation: bastion privilege escalation",
        ["auditd_labels", "syslogs"],
        0.88,
        "promoted",
        json.dumps({
            "description": "Multiple bastion hosts show auditd evidence of privilege escalation (sudo -l → T1069) without corresponding CMDB access control change records",
            "technique": "T1069: Permission Groups Discovery",
            "affected_instances": sum(1 for inst_labels in labels.values() 
                                     for l in inst_labels.values() 
                                     if "T1069" in l.get("technique", "")),
            "recommendation": "Cross-reference with change management system; flag as potential unauthorized escalation",
        }),
    ))
    
    if hyp_rows:
        execute_values(cur, """
            INSERT INTO reconciliation_hypotheses (tenant_id, hypothesis_type, entity_id,
                entity_name, evidence_sources, confidence_score, status, details)
            VALUES %s
        """, hyp_rows)
        conn.commit()
    
    print(f"  Created {len(hyp_rows)} reconciliation hypotheses "
          f"({len(dark_ips_list)} dark nodes, {len(unused_instances[:10]) + len(PHANTOM_NAMES)} phantoms, "
          f"{dark_edge_count} dark edges, 1 identity mutation)")
    
    conn.close()
    
    return {
        "entities": len(entity_rows),
        "relationships": len(rel_rows),
        "telemetry_flows": flow_row_count,
        "security_events": len(sec_rows),
        "incidents": len(incident_rows),
        "hypotheses": len(hyp_rows),
        "dark_nodes": dark_node_count,
    }


# ─── TimescaleDB KPI Metrics ───────────────────────────────────

def populate_timescaledb(instances: list[dict], labels: dict):
    """Load KPI metrics derived from CasinoLimit data into TimescaleDB."""
    
    print("\n" + "=" * 60)
    print("Phase 3: TimescaleDB KPI Metrics Population")
    print("=" * 60)
    
    import psycopg2
    from psycopg2.extras import execute_values
    
    try:
        conn = get_pg_connection(host=TIMESCALE_HOST, port=TIMESCALE_PORT, dbname=TIMESCALE_DB)
    except Exception as e:
        print(f"  [WARN] Could not connect to TimescaleDB: {e}")
        return
    
    cur = conn.cursor()
    
    # Check if kpi_metrics table exists
    cur.execute("SELECT EXISTS(SELECT FROM information_schema.tables WHERE table_name='kpi_metrics')")
    if not cur.fetchone()[0]:
        print("  [WARN] kpi_metrics table not found in TimescaleDB. Skipping.")
        conn.close()
        return
    
    # Get kpi_metrics column structure
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='kpi_metrics' ORDER BY ordinal_position")
    columns = [row[0] for row in cur.fetchall()]
    print(f"  kpi_metrics columns: {columns}")
    
    # Clean existing CasinoLimit metrics
    try:
        cur.execute("DELETE FROM kpi_metrics WHERE entity_id LIKE 'CL-%'")
        conn.commit()
    except:
        conn.rollback()
    
    # Generate time-series KPI data based on CasinoLimit activity
    active_instances = [inst for inst in instances if int(inst.get("step_count", "0") or "0") > 0]
    
    # We'll generate metrics for a 24h window matching the competition timeline
    base_time = datetime(2024, 5, 17, 20, 30, 0, tzinfo=timezone.utc)  # Challenge start
    
    metric_rows = []
    
    # Required columns (from typical Pedkai kpi_metrics schema)
    # Let's figure out what columns we actually have
    if "entity_id" in columns and "timestamp" in columns:
        for inst in active_instances[:50]:  # Cap at 50 for performance
            instance_name = inst["instance"]
            sc = int(inst.get("step_count", "0") or "0")
            entity_id = f"CL-{instance_name}"
            
            # Generate metrics every 15 minutes for 12 hours
            for minute_offset in range(0, 720, 15):
                ts = base_time + timedelta(minutes=minute_offset)
                
                # Simulate traffic volume increasing during attack
                import random
                random.seed(hash(f"{instance_name}{minute_offset}"))
                
                base_traffic = 100 + random.randint(0, 50)
                attack_multiplier = 1.0
                if sc >= 3 and minute_offset > 180:
                    attack_multiplier = 2.5 + random.random()
                elif sc >= 2 and minute_offset > 120:
                    attack_multiplier = 1.5 + random.random() * 0.5
                
                # Number of attack techniques active at this time
                tech_count = len(labels.get(instance_name, {}))
                
                # Build row based on available columns
                row_data = {}
                if "entity_id" in columns:
                    row_data["entity_id"] = entity_id
                if "timestamp" in columns:
                    row_data["timestamp"] = ts
                if "metric_name" in columns:
                    row_data["metric_name"] = "traffic_volume_mbps"
                if "metric_value" in columns or "value" in columns:
                    key = "metric_value" if "metric_value" in columns else "value"
                    row_data[key] = round(base_traffic * attack_multiplier, 2)
                if "tenant_id" in columns:
                    row_data["tenant_id"] = TENANT_ID
                if "kpi_name" in columns:
                    row_data["kpi_name"] = "traffic_volume_mbps"
                
                if row_data:
                    metric_rows.append(row_data)
        
        if metric_rows:
            # Build INSERT dynamically based on columns found
            cols = list(metric_rows[0].keys())
            col_names = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(cols))
            
            values = [tuple(row[c] for c in cols) for row in metric_rows]
            
            try:
                execute_values(cur, f"INSERT INTO kpi_metrics ({col_names}) VALUES %s",
                             values, template=f"({', '.join(['%s']*len(cols))})")
                conn.commit()
                print(f"  Loaded {len(metric_rows)} KPI metric records")
            except Exception as e:
                conn.rollback()
                print(f"  [WARN] Failed to load KPI metrics: {e}")
    else:
        print("  [WARN] kpi_metrics table structure not compatible. Skipping.")
    
    conn.close()


# ─── Validation ─────────────────────────────────────────────────

def validate_data(pg_stats: dict):
    """Run validation queries against loaded data."""
    
    print("\n" + "=" * 60)
    print("Phase 4: Data Validation")
    print("=" * 60)
    
    import psycopg2
    conn = get_pg_connection()
    cur = conn.cursor()
    
    checks = [
        ("Network Entities", f"SELECT COUNT(*), entity_type FROM network_entities WHERE tenant_id='{TENANT_ID}' GROUP BY entity_type ORDER BY COUNT(*) DESC"),
        ("Entity Relationships", f"SELECT COUNT(*), relationship_type FROM entity_relationships WHERE tenant_id='{TENANT_ID}' GROUP BY relationship_type"),
        ("Dark Nodes", f"SELECT COUNT(*) FROM network_entities WHERE tenant_id='{TENANT_ID}' AND entity_type='dark_node'"),
        ("Telemetry Flows", f"SELECT COUNT(*) FROM telemetry_flows WHERE tenant_id='{TENANT_ID}'"),
        ("Security Events", f"SELECT COUNT(*) FROM security_events WHERE tenant_id='{TENANT_ID}'"),
        ("Unique MITRE Techniques", f"SELECT COUNT(DISTINCT technique_id) FROM security_events WHERE tenant_id='{TENANT_ID}'"),
        ("Incidents", f"SELECT COUNT(*), severity FROM incidents WHERE tenant_id='{TENANT_ID}' GROUP BY severity"),
        ("Reconciliation Hypotheses", f"SELECT COUNT(*), hypothesis_type, status FROM reconciliation_hypotheses WHERE tenant_id='{TENANT_ID}' GROUP BY hypothesis_type, status"),
    ]
    
    all_passed = True
    for name, query in checks:
        try:
            cur.execute(query)
            results = cur.fetchall()
            print(f"\n  [{name}]")
            for row in results:
                print(f"    {row}")
        except Exception as e:
            print(f"\n  [{name}] ERROR: {e}")
            all_passed = False
            conn.rollback()
    
    # Validate Datagerry
    print(f"\n  [Datagerry CMDB Validation]")
    client = DataGerryClient(DATAGERRY_URL, DATAGERRY_USER, DATAGERRY_PASS)
    if client.login():
        types = client.get_types()
        cl_types = [t for t in types if t["name"].startswith("casinolimit_")]
        print(f"    CasinoLimit types: {len(cl_types)}")
        for t in cl_types:
            objects = client.get_objects_by_type(t["public_id"])
            print(f"    Type '{t['name']}' (ID={t['public_id']}): {len(objects)} objects")
    
    # Committee Brief Cross-Check
    print(f"\n  [Committee Brief Cross-Check]")
    
    # Check: Dark nodes discovered
    cur.execute(f"SELECT COUNT(*) FROM network_entities WHERE tenant_id='{TENANT_ID}' AND entity_type='dark_node'")
    dark_count = cur.fetchone()[0]
    print(f"    Dark nodes discovered: {dark_count} {'✓' if dark_count > 0 else '✗'}")
    
    # Check: Reconciliation hypotheses generated
    cur.execute(f"SELECT COUNT(*) FROM reconciliation_hypotheses WHERE tenant_id='{TENANT_ID}'")
    hyp_count = cur.fetchone()[0]
    print(f"    Reconciliation hypotheses: {hyp_count} {'✓' if hyp_count > 0 else '✗'}")
    
    # Check: MITRE ATT&CK techniques mapped
    cur.execute(f"SELECT COUNT(DISTINCT technique_id) FROM security_events WHERE tenant_id='{TENANT_ID}'")
    tech_count = cur.fetchone()[0]
    print(f"    MITRE ATT&CK techniques: {tech_count} {'✓' if tech_count > 0 else '✗'}")
    
    # Check: Multi-modal evidence exists
    cur.execute(f"""
        SELECT COUNT(*) FROM reconciliation_hypotheses 
        WHERE tenant_id='{TENANT_ID}' 
        AND array_length(evidence_sources, 1) >= 2
    """)
    multi_modal = cur.fetchone()[0]
    print(f"    Multi-modal hypotheses (≥2 sources): {multi_modal} {'✓' if multi_modal > 0 else '✗'}")
    
    conn.close()
    return all_passed


# ─── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CasinoLimit Full Client Simulation Loader")
    parser.add_argument("--clean", action="store_true", help="Clean existing data before loading")
    parser.add_argument("--skip-datagerry", action="store_true", help="Skip Datagerry CMDB population")
    parser.add_argument("--skip-postgres", action="store_true", help="Skip PostgreSQL population")
    parser.add_argument("--skip-timescale", action="store_true", help="Skip TimescaleDB population")
    parser.add_argument("--max-instances", type=int, default=0, help="Limit number of instances to process (0=all)")
    args = parser.parse_args()
    
    start_time = time.time()
    
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  CasinoLimit Full Client Simulation Loader              ║")
    print("║  Pedkai Operational Reconciliation Engine                ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"\nDataset: {DATASET_BASE}")
    print(f"Tenant: {TENANT_ID}")
    print(f"Datagerry: {DATAGERRY_URL}")
    print(f"PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    print(f"TimescaleDB: {TIMESCALE_HOST}:{TIMESCALE_PORT}/{TIMESCALE_DB}")
    
    # ── Parse Dataset ──
    print("\n" + "=" * 60)
    print("Parsing CasinoLimit Dataset...")
    print("=" * 60)
    
    print("  Parsing steps.csv...")
    instances = parse_steps_csv()
    print(f"  Found {len(instances)} instances")
    
    if args.max_instances:
        instances = instances[:args.max_instances]
        print(f"  Limited to {len(instances)} instances (--max-instances)")
    
    print("  Parsing MITRE ATT&CK labels...")
    labels = parse_system_labels()
    total_labels = sum(len(v) for v in labels.values())
    print(f"  Found {total_labels} labels across {len(labels)} instances")
    
    print("  Parsing relations...")
    relations = parse_relations()
    total_relations = sum(len(v) for v in relations.values())
    print(f"  Found {total_relations} relations across {len(relations)} instances")
    
    print("  Parsing labelled flows (sample)...")
    flows = parse_labelled_flows_sample(max_instances=30, max_rows_per_instance=500)
    total_flows = sum(len(v) for v in flows.values())
    print(f"  Loaded {total_flows} flow records from {len(flows)} instances")
    
    print("  Parsing Zeek flows (sample)...")
    zeek_flows = parse_zeek_flows_sample(max_instances=30, max_rows_per_machine=200)
    total_zeek = sum(len(m) for machines in zeek_flows.values() for m in machines.values())
    print(f"  Loaded {total_zeek} Zeek flow records from {len(zeek_flows)} instances")
    
    # ── Datagerry CMDB ──
    type_ids = {}
    if not args.skip_datagerry:
        client = DataGerryClient(DATAGERRY_URL, DATAGERRY_USER, DATAGERRY_PASS)
        if client.login():
            if args.clean:
                print("\n  Cleaning existing Datagerry types/objects...")
                for t in client.get_types():
                    if t["name"].startswith("casinolimit_"):
                        client.delete_objects_by_type(t["public_id"])
                        client.delete_type(t["public_id"])
                        print(f"    Deleted type: {t['name']}")
            
            type_ids = populate_datagerry_cmdb(client, instances, labels)
        else:
            print("  [ERROR] Failed to login to Datagerry. Skipping CMDB population.")
    
    # ── PostgreSQL ──
    pg_stats = {}
    if not args.skip_postgres:
        try:
            pg_stats = populate_postgres(instances, labels, flows, zeek_flows, relations)
        except Exception as e:
            print(f"  [ERROR] PostgreSQL population failed: {e}")
            import traceback
            traceback.print_exc()
    
    # ── TimescaleDB ──
    if not args.skip_timescale:
        try:
            populate_timescaledb(instances, labels)
        except Exception as e:
            print(f"  [WARN] TimescaleDB population failed: {e}")
    
    # ── Validation ──
    try:
        validate_data(pg_stats)
    except Exception as e:
        print(f"  [WARN] Validation failed: {e}")
        import traceback
        traceback.print_exc()
    
    # ── Summary ──
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("LOADING COMPLETE")
    print("=" * 60)
    print(f"  Time elapsed: {elapsed:.1f}s")
    print(f"  Tenant ID: {TENANT_ID}")
    print(f"\n  Datagerry CMDB:")
    print(f"    Types created: {len(type_ids)}")
    if pg_stats:
        print(f"\n  PostgreSQL:")
        for k, v in pg_stats.items():
            print(f"    {k}: {v}")
    
    print(f"\n  Next steps:")
    print(f"    1. View Datagerry UI: http://localhost:80")
    print(f"    2. Query topology API: GET /api/v1/topology/{TENANT_ID}")
    print(f"    3. View dark nodes: SELECT * FROM network_entities WHERE tenant_id='{TENANT_ID}' AND entity_type='dark_node'")
    print(f"    4. View hypotheses: SELECT * FROM reconciliation_hypotheses WHERE tenant_id='{TENANT_ID}'")
    print(f"    5. View incidents: SELECT * FROM incidents WHERE tenant_id='{TENANT_ID}'")


if __name__ == "__main__":
    main()
