"""LiveTestData: loader and adapter for telecom_ts dataset in Pedkai testing."""

from .loader import (
    load_dataset_rows,
    iter_rows,
    get_cache_dir,
    NUMERIC_KPI_KEYS,
    DATASET_ID,
    DEFAULT_SMOKE_ROWS,
)
from .adapter import (
    row_to_metric_events,
    row_to_bulk_metrics,
    row_to_decision_context,
    entity_id_for_row,
    get_scenario_rows,
    data_quality_report,
)

__all__ = [
    "load_dataset_rows",
    "iter_rows",
    "get_cache_dir",
    "NUMERIC_KPI_KEYS",
    "DATASET_ID",
    "DEFAULT_SMOKE_ROWS",
    "row_to_metric_events",
    "row_to_bulk_metrics",
    "row_to_decision_context",
    "entity_id_for_row",
    "get_scenario_rows",
    "data_quality_report",
]
