"""
LiveTestData fixtures: mock row for tests that run without HuggingFace.

Use this for CI and fast unit/validation tests. For full dataset use
LiveTestData.load_dataset_rows() with cache (LIVETESTDATA_CACHE or HF_DATASETS_CACHE).
"""

# Minimal mock row: 30 points, 3 numeric KPIs (RSRP, DL_BLER, UL_BLER), Jamming anomaly.
# Matches adapter contract: start_time, sampling_rate, KPIs (numeric), labels, anomalies.
MOCK_ROW = {
    "start_time": "2025-01-01 00:05:33.000",
    "end_time": "2025-01-01 00:05:36.000",
    "sampling_rate": 10,
    "KPIs": {
        "RSRP": [-73.0] * 15 + [-85.0, -86.0, -87.0] + [-73.0] * 12,
        "DL_BLER": [0.001] * 12 + [0.05, 0.06, 0.07] + [0.001] * 15,
        "UL_BLER": [0.02] * 12 + [0.12, 0.15, 0.17] + [0.02] * 15,
    },
    "description": "RSRP dip and BLER increase in middle of window.",
    "anomalies": {
        "exists": True,
        "type": "Jamming",
        "anomaly_duration": {"start": 12, "end": 18},
        "affected_kpis": ["DL_BLER", "UL_BLER", "RSRP"],
        "troubleshooting_tickets": "Jamming suspected; check interference.",
    },
    "labels": {"zone": "A", "application": "File", "mobility": "No", "congestion": "No", "anomaly_present": "Yes"},
    "statistics": {
        "RSRP": {"mean": -75.0, "variance": 20.0, "trend": 0, "periodicity": 30},
        "DL_BLER": {"mean": 0.02, "variance": 0.001, "trend": 0, "periodicity": 30},
        "UL_BLER": {"mean": 0.05, "variance": 0.002, "trend": 0, "periodicity": 30},
    },
}


def get_mock_row():
    """Return a copy of MOCK_ROW so tests do not mutate shared state."""
    import copy
    from datetime import datetime, timezone, timedelta
    
    row = copy.deepcopy(MOCK_ROW)
    # Use recent timestamp so baseline query (last 24 hours) finds this data
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)
    row["start_time"] = start.isoformat()
    row["end_time"] = (start + timedelta(seconds=3)).isoformat()
    return row
