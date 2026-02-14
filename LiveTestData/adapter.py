"""
LiveTestData adapter: map dataset rows to Pedkai event and bulk shapes.

Entity semantics: each row is one logical observation point (cell-level in RAN context).
Adapter contract: entity_id is cell-level (CELL_LIVE_{zone}_{idx}) unless overridden.

Replay timestamp rule: timestamp = start_time + (index / sampling_rate) for deterministic
idempotency (same row replayed twice => same PKs).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .loader import NUMERIC_KPI_KEYS


def _parse_start_time(row: dict) -> datetime:
    """Parse start_time string to timezone-aware datetime."""
    st = row.get("start_time") or "2025-01-01 00:00:00.000"
    if isinstance(st, str):
        # Assume UTC if no TZ
        if "Z" in st or "+" in st or st.endswith("UTC"):
            return datetime.fromisoformat(st.replace("Z", "+00:00"))
        return datetime.strptime(st[:26], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    return st if getattr(st, "tzinfo", None) else st.replace(tzinfo=timezone.utc)


def _get_numeric_kpis(row: dict) -> Dict[str, List[float]]:
    """Return only numeric KPI series; skip NaN/invalid."""
    kpis = row.get("KPIs") or {}
    out = {}
    for k in NUMERIC_KPI_KEYS:
        if k not in kpis:
            continue
        vals = kpis[k]
        if not vals:
            continue
        try:
            cleaned = [float(x) if x is not None and str(x).lower() != "nan" else None for x in vals]
            if all(v is None for v in cleaned):
                continue
            out[k] = cleaned
        except (TypeError, ValueError):
            continue
    return out


def row_to_metric_events(
    row: dict,
    entity_id: str,
    tenant_id: str = "live-test",
    time_compression_sec: Optional[float] = None,
) -> List[dict]:
    """
    Convert one LiveTestData row to a list of metric events for handle_metrics_event.

    Each event has: entity_id, tenant_id, metrics (dict of metric_name -> single value), timestamp.
    Timestamp rule: start_time + (index / sampling_rate) for deterministic idempotency.
    If time_compression_sec is set, timestamps are still derived from start_time + index/sampling_rate
    but wall-clock replay can use this interval (document only; caller controls replay speed).
    """
    start = _parse_start_time(row)
    rate = int(row.get("sampling_rate") or 10)
    kpis = _get_numeric_kpis(row)
    if not kpis:
        return []

    n = len(next(iter(kpis.values())))
    events = []
    for t in range(n):
        ts = start + timedelta(seconds=t / rate)
        metrics = {}
        for name, series in kpis.items():
            if t < len(series) and series[t] is not None:
                metrics[name] = series[t]
        if not metrics:
            continue
        events.append({
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "metrics": metrics,
            "timestamp": ts.isoformat(),
        })
    return events


def row_to_bulk_metrics(
    row: dict,
    entity_id: str,
    tenant_id: str = "live-test",
) -> List[dict]:
    """
    Convert one row to list of (tenant_id, entity_id, metric_name, value, timestamp) for bulk insert.

    Schema matches KPIMetricORM: tenant_id, entity_id, timestamp, metric_name, value, tags.
    Timestamp rule: start_time + (index / sampling_rate). Deterministic per (row, timestep_index).
    One row => one entity × 127 timesteps × 20 numeric KPIs => 2,540 rows (typical).
    """
    start = _parse_start_time(row)
    rate = int(row.get("sampling_rate") or 10)
    kpis = _get_numeric_kpis(row)
    if not kpis:
        return []

    rows_out = []
    n = len(next(iter(kpis.values())))
    for t in range(n):
        ts = start + timedelta(seconds=t / rate)
        for name, series in kpis.items():
            if t >= len(series):
                continue
            v = series[t]
            if v is None or (isinstance(v, float) and (v != v)):  # NaN
                continue
            rows_out.append({
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "metric_name": name,
                "value": float(v),
                "timestamp": ts,
                "tags": {"source": "live_test_data"},
            })
    return rows_out


def entity_id_for_row(row: dict, idx: int) -> str:
    """Default entity_id: CELL_LIVE_{zone}_{idx}. Cell-level semantics."""
    labels = row.get("labels") or {}
    zone = labels.get("zone", "X")
    return f"CELL_LIVE_{zone}_{idx}"


def get_scenario_rows(
    rows: List[dict],
    anomaly_type: Optional[str] = None,
    zone: Optional[str] = None,
    anomaly_present: Optional[bool] = None,
) -> List[tuple[int, dict]]:
    """Filter rows by anomaly_type, zone, anomaly_present. Returns (index, row) list."""
    out = []
    for i, row in enumerate(rows):
        anom = row.get("anomalies") or {}
        if anomaly_type is not None and anom.get("type") != anomaly_type:
            continue
        labels = row.get("labels") or {}
        if zone is not None and labels.get("zone") != zone:
            continue
        if anomaly_present is not None:
            ap = labels.get("anomaly_present")
            if str(ap).lower() in ("yes", "true", "1"):
                ap_val = True
            elif str(ap).lower() in ("no", "false", "0"):
                ap_val = False
            else:
                ap_val = bool(anom.get("exists"))
            if ap_val != anomaly_present:
                continue
        out.append((i, row))
    return out


def row_to_decision_context(row: dict, dataset_id: str = "live-test") -> dict:
    """
    Build DecisionTraceCreate-like context from row (description, labels, troubleshooting_tickets).
    """
    labels = row.get("labels") or {}
    anom = row.get("anomalies") or {}
    stats = row.get("statistics") or {}
    kpi_snapshot = {}
    for k, v in list(stats.items())[:10]:
        if isinstance(v, dict) and "mean" in v:
            kpi_snapshot[k] = v.get("mean")

    return {
        "tenant_id": f"{dataset_id}-global",
        "trigger_type": "alarm" if anom.get("exists") else "manual",
        "trigger_description": (row.get("description") or "Telecom network event")[:500],
        "context": {
            "affected_entities": [f"CELL_LIVE_{labels.get('zone', 'X')}_0"],
            "kpi_snapshot": kpi_snapshot or None,
            "troubleshooting_tickets": anom.get("troubleshooting_tickets"),
            "labels": labels,
        },
        "decision_summary": (anom.get("troubleshooting_tickets") or row.get("description") or "Processed")[:300],
        "tradeoff_rationale": "Based on LiveTestData row analysis.",
        "action_taken": "NO_ACTION",
        "decision_maker": "system:pedkai-live-test",
        "confidence_score": 0.8,
        "domain": "anops",
        "tags": ["live_test_data", labels.get("zone", "X"), anom.get("type") or "normal"],
    }


def data_quality_report(rows: List[dict], kpi_subset: Optional[List[str]] = None) -> dict:
    """Per-KPI null count and min/max over first N rows. Optional guard: fail if null rate > X%."""
    kpis_to_check = kpi_subset or NUMERIC_KPI_KEYS[:8]
    report = {"rows_checked": len(rows), "per_kpi": {}}
    for k in kpis_to_check:
        nulls = 0
        total = 0
        vals = []
        for row in rows:
            series = (row.get("KPIs") or {}).get(k)
            if not series:
                continue
            for v in series:
                total += 1
                if v is None or (isinstance(v, float) and (v != v)):
                    nulls += 1
                else:
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        nulls += 1
        rate = (nulls / total * 100) if total else 0
        report["per_kpi"][k] = {
            "null_count": nulls,
            "total": total,
            "null_rate_pct": round(rate, 2),
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }
    return report
