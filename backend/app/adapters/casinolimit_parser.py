"""CasinoLimit telemetry parser.

Normalises three CasinoLimit streams into Pedk.ai's UnifiedSignal format:
  - Network flows: {src_ip, dst_ip, src_port, dst_port, protocol, bytes, packets, timestamp}
  - Syscalls: {process_id, syscall_name, args, return_code, timestamp, host_id}
  - MITRE labels: {timestamp, host_id, technique_id, tactic, confidence}
"""
import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class UnifiedSignal:
    entity_id: Optional[str]      # CMDB entity ID (None if dark/unknown)
    signal_type: str              # 'network_flow', 'syscall', 'mitre_label'
    timestamp: datetime
    payload: dict
    source: str                   # 'casinolimit'
    is_dark: bool = False         # True if entity_id is None (unknown entity)


@dataclass
class CMDBSnapshot:
    """Minimal CMDB representation for IP/host → entity_id mapping."""
    ip_to_entity: dict = field(default_factory=dict)    # ip → entity_id
    host_to_entity: dict = field(default_factory=dict)  # host_id → entity_id


@dataclass
class EnrichedSignal:
    signal: UnifiedSignal
    cmdb_entity: Optional[dict]  # matched CMDB entry or None
    divergence_findings: list = field(default_factory=list)


class CasinoLimitParser:
    def __init__(self):
        pass

    def _parse_timestamp(self, ts) -> datetime:
        """Parse timestamp from various formats."""
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                try:
                    return datetime.fromtimestamp(float(ts), tz=timezone.utc)
                except Exception:
                    return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)

    def parse_network_flows(self, filepath: str) -> list[UnifiedSignal]:
        """Parse network flow records → UnifiedSignal list.

        Supports CSV and JSON. Skips malformed records with a warning.
        entity_id is None for flows (IP-based; enrichment resolves to entity).
        is_dark=True because all flows from unknown IPs are initially dark.
        """
        signals = []
        try:
            if filepath.endswith(".json"):
                with open(filepath) as f:
                    records = json.load(f)
            else:
                df = pd.read_csv(filepath)
                records = df.to_dict("records")

            for record in records:
                try:
                    ts = self._parse_timestamp(record.get("timestamp", 0))
                    signals.append(UnifiedSignal(
                        entity_id=None,
                        signal_type="network_flow",
                        timestamp=ts,
                        payload={
                            "src_ip": record.get("src_ip"),
                            "dst_ip": record.get("dst_ip"),
                            "src_port": record.get("src_port"),
                            "dst_port": record.get("dst_port"),
                            "protocol": record.get("protocol"),
                            "bytes": record.get("bytes", 0),
                            "packets": record.get("packets", 0),
                        },
                        source="casinolimit",
                        is_dark=True,  # IP unknown until enriched
                    ))
                except Exception as e:
                    logger.warning(f"Skipping malformed network flow record: {e}")
        except Exception as e:
            logger.error(f"Failed to parse network flows from {filepath}: {e}")
        return signals

    def parse_syscalls(self, filepath: str) -> list[UnifiedSignal]:
        """Parse syscall records → UnifiedSignal list."""
        signals = []
        try:
            if filepath.endswith(".json"):
                with open(filepath) as f:
                    records = json.load(f)
            else:
                df = pd.read_csv(filepath)
                records = df.to_dict("records")

            for record in records:
                try:
                    ts = self._parse_timestamp(record.get("timestamp", 0))
                    host_id = str(record.get("host_id", ""))
                    signals.append(UnifiedSignal(
                        entity_id=host_id if host_id else None,
                        signal_type="syscall",
                        timestamp=ts,
                        payload={
                            "process_id": record.get("process_id"),
                            "syscall_name": record.get("syscall_name"),
                            "args": record.get("args"),
                            "return_code": record.get("return_code"),
                            "host_id": host_id,
                        },
                        source="casinolimit",
                        is_dark=(not host_id),
                    ))
                except Exception as e:
                    logger.warning(f"Skipping malformed syscall record: {e}")
        except Exception as e:
            logger.error(f"Failed to parse syscalls from {filepath}: {e}")
        return signals

    def parse_mitre_labels(self, filepath: str) -> list[UnifiedSignal]:
        """Parse MITRE ATT&CK labels → UnifiedSignal list."""
        signals = []
        try:
            if filepath.endswith(".json"):
                with open(filepath) as f:
                    records = json.load(f)
            else:
                df = pd.read_csv(filepath)
                records = df.to_dict("records")

            for record in records:
                try:
                    ts = self._parse_timestamp(record.get("timestamp", 0))
                    host_id = str(record.get("host_id", ""))
                    signals.append(UnifiedSignal(
                        entity_id=host_id if host_id else None,
                        signal_type="mitre_label",
                        timestamp=ts,
                        payload={
                            "host_id": host_id,
                            "technique_id": record.get("technique_id"),
                            "tactic": record.get("tactic"),
                            "confidence": float(record.get("confidence", 1.0)),
                        },
                        source="casinolimit",
                        is_dark=(not host_id),
                    ))
                except Exception as e:
                    logger.warning(f"Skipping malformed MITRE label record: {e}")
        except Exception as e:
            logger.error(f"Failed to parse MITRE labels from {filepath}: {e}")
        return signals

    def enrich_with_cmdb(self, signals: list[UnifiedSignal], cmdb: CMDBSnapshot) -> list[EnrichedSignal]:
        """Cross-reference signals with CMDB to resolve entity_ids.

        Unmatched signals are marked as potential Dark Node evidence.
        """
        enriched = []
        for signal in signals:
            matched_entity = None
            resolved_entity_id = signal.entity_id

            if signal.signal_type == "network_flow":
                src_ip = signal.payload.get("src_ip")
                if src_ip and src_ip in cmdb.ip_to_entity:
                    resolved_entity_id = cmdb.ip_to_entity[src_ip]
                    signal.entity_id = resolved_entity_id
                    signal.is_dark = False
                    matched_entity = {"entity_id": resolved_entity_id, "type": "network_entity"}

            elif signal.signal_type in ("syscall", "mitre_label"):
                host_id = signal.payload.get("host_id")
                if host_id and host_id in cmdb.host_to_entity:
                    resolved_entity_id = cmdb.host_to_entity[host_id]
                    signal.entity_id = resolved_entity_id
                    signal.is_dark = False
                    matched_entity = {"entity_id": resolved_entity_id, "type": "host"}

            findings = []
            if signal.is_dark:
                findings.append({"type": "DARK_NODE_CANDIDATE", "signal_type": signal.signal_type})
            if signal.signal_type == "mitre_label":
                findings.append({"type": "INTRUSION_CANDIDATE",
                                  "technique": signal.payload.get("technique_id"),
                                  "confidence": signal.payload.get("confidence", 1.0)})

            enriched.append(EnrichedSignal(signal=signal, cmdb_entity=matched_entity, divergence_findings=findings))

        return enriched
