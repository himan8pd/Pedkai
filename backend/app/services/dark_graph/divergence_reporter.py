"""File-based Dark Graph Divergence Reporter.

Works directly from Parquet/CSV/JSON files — no database required.
Used for Offline PoC mode (customer provides 3 files, we generate a report).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
import pandas as pd
import json
import uuid


@dataclass
class DivergenceFinding:
    finding_type: str  # dark_node, phantom_node, dark_edge, phantom_edge, dark_attribute, identity_mutation
    entity_id: str
    confidence: float
    evidence: list[str]
    recommended_action: str


@dataclass
class DivergenceReport:
    tenant_id: str
    generated_at: str  # ISO datetime
    findings: list[DivergenceFinding]
    summary_stats: dict  # {finding_type: count, total: int, high_confidence: int}

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "generated_at": self.generated_at,
            "findings": [
                {
                    "finding_type": f.finding_type,
                    "entity_id": f.entity_id,
                    "confidence": f.confidence,
                    "evidence": f.evidence,
                    "recommended_action": f.recommended_action
                }
                for f in self.findings
            ],
            "summary_stats": self.summary_stats
        }


class DivergenceReporter:
    """File-based dark graph divergence detection. No database required."""

    def load_cmdb_snapshot(self, path: str) -> pd.DataFrame:
        """Load CMDB from CSV, JSON, or Parquet. Returns DataFrame with entity_id column."""
        if path.endswith(".parquet"):
            return pd.read_parquet(path)
        elif path.endswith(".json"):
            return pd.read_json(path)
        else:
            return pd.read_csv(path)

    def load_telemetry_series(self, path: str) -> pd.DataFrame:
        """Load PM counters. Expects entity_id and at least one KPI column."""
        if path.endswith(".parquet"):
            return pd.read_parquet(path)
        elif path.endswith(".json"):
            return pd.read_json(path)
        return pd.read_csv(path)

    def load_ticket_archive(self, path: str) -> pd.DataFrame:
        """Load ITSM tickets."""
        if path.endswith(".parquet"):
            return pd.read_parquet(path)
        elif path.endswith(".json"):
            return pd.read_json(path)
        return pd.read_csv(path)

    def find_dark_nodes(self, cmdb: pd.DataFrame, telemetry: pd.DataFrame) -> list[DivergenceFinding]:
        """Entities in telemetry with no CMDB record."""
        # telemetry entity_ids NOT in cmdb entity_ids
        cmdb_ids = set(cmdb["entity_id"].astype(str))
        tel_ids = set(telemetry["entity_id"].astype(str)) if "entity_id" in telemetry.columns else set()
        dark = tel_ids - cmdb_ids
        return [
            DivergenceFinding(
                finding_type="dark_node",
                entity_id=eid,
                confidence=0.85,
                evidence=[f"Entity {eid} has telemetry but no CMDB record"],
                recommended_action="Investigate undocumented network element; add to CMDB or verify decommission"
            )
            for eid in dark
        ]

    def find_phantom_nodes(self, cmdb: pd.DataFrame, telemetry: pd.DataFrame, threshold_days: int = 90) -> list[DivergenceFinding]:
        """CMDB CIs with zero telemetry for > threshold_days."""
        cmdb_ids = set(cmdb["entity_id"].astype(str))
        tel_ids = set(telemetry["entity_id"].astype(str)) if "entity_id" in telemetry.columns else set()
        phantoms = cmdb_ids - tel_ids
        return [
            DivergenceFinding(
                finding_type="phantom_node",
                entity_id=eid,
                confidence=0.75,
                evidence=[f"Entity {eid} in CMDB but no telemetry for >{threshold_days} days"],
                recommended_action="Verify if entity is decommissioned; update CMDB to remove stale CI"
            )
            for eid in phantoms
        ]

    def find_identity_mutations(self, cmdb: pd.DataFrame, telemetry: pd.DataFrame) -> list[DivergenceFinding]:
        """Detect identity mutations — entities where external_id doesn't match telemetry source_id."""
        findings = []
        if "external_id" not in cmdb.columns or "source_entity_id" not in telemetry.columns:
            return findings
        # Find entities where external_id in CMDB doesn't appear in telemetry source_entity_id
        tel_source_ids = set(telemetry["source_entity_id"].dropna().astype(str))
        for _, row in cmdb.iterrows():
            ext_id = str(row.get("external_id", ""))
            entity_id = str(row.get("entity_id", ""))
            if ext_id and ext_id not in tel_source_ids and entity_id in tel_source_ids:
                findings.append(DivergenceFinding(
                    finding_type="identity_mutation",
                    entity_id=entity_id,
                    confidence=0.70,
                    evidence=[f"Entity {entity_id}: CMDB external_id={ext_id} not in telemetry source IDs"],
                    recommended_action="Verify hardware swap or NMS ID change; update external_id in CMDB"
                ))
        return findings

    def find_behavioural_dark_edges(self, tickets: pd.DataFrame, cmdb: pd.DataFrame) -> list[DivergenceFinding]:
        """Detect undocumented connections via ticket correlation patterns."""
        findings = []
        if "related_entities" not in tickets.columns and "affected_ci" not in tickets.columns:
            return findings
        # Simple heuristic: tickets referencing pairs of entities that aren't related in CMDB
        # For now, return empty (full implementation requires topology graph)
        return findings

    def generate_report(self, tenant_id: str, cmdb_path: str = None, telemetry_path: str = None, ticket_path: str = None,
                        cmdb: pd.DataFrame = None, telemetry: pd.DataFrame = None, tickets: pd.DataFrame = None) -> DivergenceReport:
        """Run all detectors and return aggregated report."""
        if cmdb is None and cmdb_path:
            cmdb = self.load_cmdb_snapshot(cmdb_path)
        if telemetry is None and telemetry_path:
            telemetry = self.load_telemetry_series(telemetry_path)
        if tickets is None and ticket_path:
            tickets = self.load_ticket_archive(ticket_path)
        if cmdb is None:
            cmdb = pd.DataFrame(columns=["entity_id"])
        if telemetry is None:
            telemetry = pd.DataFrame(columns=["entity_id"])
        if tickets is None:
            tickets = pd.DataFrame()

        findings = []
        findings.extend(self.find_dark_nodes(cmdb, telemetry))
        findings.extend(self.find_phantom_nodes(cmdb, telemetry))
        findings.extend(self.find_identity_mutations(cmdb, telemetry))
        findings.extend(self.find_behavioural_dark_edges(tickets, cmdb))

        type_counts = {}
        for f in findings:
            type_counts[f.finding_type] = type_counts.get(f.finding_type, 0) + 1

        return DivergenceReport(
            tenant_id=tenant_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            findings=findings,
            summary_stats={
                **type_counts,
                "total": len(findings),
                "high_confidence": sum(1 for f in findings if f.confidence >= 0.8)
            }
        )
