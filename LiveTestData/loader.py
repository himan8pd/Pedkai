"""
LiveTestData loader for Pedkai testing.

Loads the telecom time-series dataset (HuggingFace AliMaatouk/telecom_ts or local cache).
Dataset version pin: AliMaatouk/telecom_ts (document for CI cache refresh).
"""

import os
from typing import Any, Iterator, List, Optional

# Numeric KPI keys only (exclude UL_Protocol, DL_Protocol for anomaly/causal path)
NUMERIC_KPI_KEYS = [
    "RSRP", "DL_BLER", "DL_MCS", "UL_BLER", "UL_MCS", "UL_NPRB", "UL_SNR",
    "TX_Bytes", "RX_Bytes", "Estimated_UL_Buffer", "PRBs_DL_Current",
    "PRBs_UL_Current", "PRB_Utilization_DL", "PRB_Utilization_UL",
    "UL_NumberOfPackets", "DL_NumberOfPackets",
]

DATASET_ID = "AliMaatouk/telecom_ts"
DEFAULT_SPLIT = "train"
DEFAULT_SMOKE_ROWS = 100
def get_cache_dir() -> Optional[str]:
    """Cache dir from env for CI; avoids HuggingFace download if cached."""
    return os.environ.get("LIVETESTDATA_CACHE") or os.environ.get("HF_DATASETS_CACHE")


def load_dataset_rows(
    split: str = DEFAULT_SPLIT,
    limit: Optional[int] = None,
    cache_dir: Optional[str] = None,
) -> List[dict]:
    """
    Load telecom_ts dataset and return list of row dicts.

    Each row has: start_time, end_time, sampling_rate, KPIs, description,
    anomalies, statistics, labels, QnA (schema aligned to dataset_info_pretty.json).

    Args:
        split: Dataset split (default train).
        limit: Max rows to return (default None = all). Use 100-500 for smoke.
        cache_dir: Override for HF cache (e.g. tests/data/cache).
    """
    from datasets import load_dataset

    cache = cache_dir or get_cache_dir()
    kwargs = {"path": DATASET_ID, "split": split}
    if cache:
        kwargs["cache_dir"] = cache

    ds = load_dataset(**kwargs)
    rows = []
    for i, item in enumerate(ds):
        if limit is not None and i >= limit:
            break
        # Convert to dict (datasets returns batch columns)
        row = {k: item[k] for k in item.keys()}
        rows.append(row)
    return rows


def iter_rows(
    split: str = DEFAULT_SPLIT,
    limit: Optional[int] = None,
    cache_dir: Optional[str] = None,
) -> Iterator[tuple[int, dict]]:
    """Yield (index, row) for memory-safe iteration (e.g. full 32k)."""
    from datasets import load_dataset

    cache = cache_dir or get_cache_dir()
    kwargs = {"path": DATASET_ID, "split": split}
    if cache:
        kwargs["cache_dir"] = cache

    ds = load_dataset(**kwargs)
    for i in range(len(ds)):
        if limit is not None and i >= limit:
            break
        item = ds[i]
        row = {k: item[k] for k in item.keys()}
        yield i, row
