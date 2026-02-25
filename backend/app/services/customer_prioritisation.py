"""
Customer Prioritisation Service — Task 7.3 (Amendment #21)

Configurable customer prioritisation for incident impact assessment.
Strategy is set via CUSTOMER_PRIORITISATION_STRATEGY env var (default: revenue).

Supported strategies:
  revenue        — Sort by monthly_fee descending (default)
  sla_tier       — Sort by SLA tier: platinum > gold > silver > bronze
  churn_risk     — Sort by churn_risk_score descending
  emergency_first — Emergency service customers first, then by revenue
"""
from enum import Enum
from typing import List
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class PrioritisationStrategy(str, Enum):
    REVENUE = "revenue"
    SLA_TIER = "sla_tier"
    CHURN_RISK = "churn_risk"
    EMERGENCY_FIRST = "emergency_first"


def prioritise_customers(
    customers: List[dict],
    strategy: PrioritisationStrategy = PrioritisationStrategy.REVENUE,
) -> List[dict]:
    """
    Sort a list of customer dicts according to the given prioritisation strategy.

    Expected dict keys (all optional — missing keys use safe defaults):
        monthly_fee: float
        sla_tier: str  ("platinum", "gold", "silver", "bronze")
        churn_risk_score: float  (0.0 – 1.0)
        is_emergency_service: bool

    Returns the sorted list (does not mutate the input).
    """
    if not customers:
        return customers

    if strategy == PrioritisationStrategy.REVENUE:
        return sorted(customers, key=lambda c: c.get("monthly_fee", 0) or 0, reverse=True)

    elif strategy == PrioritisationStrategy.SLA_TIER:
        tier_order = {"platinum": 0, "gold": 1, "silver": 2, "bronze": 3}
        return sorted(
            customers,
            key=lambda c: tier_order.get(c.get("sla_tier", "bronze"), 99),
        )

    elif strategy == PrioritisationStrategy.CHURN_RISK:
        return sorted(
            customers,
            key=lambda c: c.get("churn_risk_score", 0) or 0,
            reverse=True,
        )

    elif strategy == PrioritisationStrategy.EMERGENCY_FIRST:
        # Emergency service customers always first, then by revenue within each group
        return sorted(
            customers,
            key=lambda c: (
                0 if c.get("is_emergency_service") else 1,
                -(c.get("monthly_fee", 0) or 0),
            ),
        )

    logger.warning(f"Unknown prioritisation strategy '{strategy}' — falling back to revenue")
    return sorted(customers, key=lambda c: c.get("monthly_fee", 0) or 0, reverse=True)


def get_strategy_from_settings() -> PrioritisationStrategy:
    """Load the configured strategy from application settings."""
    from backend.app.core.config import get_settings
    settings = get_settings()
    try:
        return PrioritisationStrategy(settings.customer_prioritisation_strategy)
    except ValueError:
        logger.warning(
            f"Invalid CUSTOMER_PRIORITISATION_STRATEGY "
            f"'{settings.customer_prioritisation_strategy}' — defaulting to revenue"
        )
        return PrioritisationStrategy.REVENUE
