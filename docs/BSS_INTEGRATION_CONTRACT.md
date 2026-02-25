# BSS Integration Contract

**Version**: 1.0
**Status**: Draft
**Owner**: Platform Architecture
**Last Updated**: 2026-02-25

---

## 1. Purpose

This document defines the contract between Pedkai and external BSS (Business Support Systems) providers. Any BSS adapter must implement the `BSSAdapter` abstract base class defined in [`bss_adapter.py`](../backend/app/services/bss_adapter.py).

## 2. Required Interface

All BSS adapters MUST implement the following three methods:

### 2.1 `get_billing_account(customer_id: UUID) → BillingAccountInfo | None`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | UUID | ✅ | Pedkai internal customer ID |
| `account_id` | UUID | ❌ | BSS-side account identifier |
| `plan_name` | str | ❌ | Service plan display name |
| `monthly_fee` | float | ❌ | Monthly recurring charge |
| `currency` | str | ✅ | ISO 4217 currency code (default: `GBP`) |

**Error handling**: Return `None` if customer not found. Do NOT raise exceptions for missing customers.

### 2.2 `get_revenue_at_risk(customer_ids: List[UUID]) → RevenueResult`

Calculates aggregate revenue at risk for a set of impacted customers.

| Field | Type | Description |
|-------|------|-------------|
| `total_revenue_at_risk` | float \| None | Sum of monthly fees for priced customers. `None` if no priced customers. |
| `is_estimate` | bool | **MANDATORY**. `True` for mock/estimated data, `False` for live BSS data. |
| `source` | str | Adapter identifier: `"mock"`, `"bss_local"`, `"amdocs"`, `"cerillion"`, etc. |
| `priced_customer_count` | int | Customers with known billing data |
| `unpriced_customer_count` | int | Customers without billing data |
| `requires_manual_valuation` | bool | `True` if any customer lacks billing data |

> [!IMPORTANT]
> **No fallback ARPU**. If a customer has no billing data, they MUST be counted as `unpriced`. Do NOT substitute an estimated ARPU — this creates false precision in revenue figures.

### 2.3 `check_disputes(customer_ids: List[UUID]) → List[UUID]`

Returns customer IDs with active billing disputes in the last 30 days. Used to adjust priority scoring.

## 3. Authentication

BSS adapters connecting to external systems must:
- Use mutual TLS or OAuth2 client credentials
- Store credentials in environment variables, never in code
- Support credential rotation without service restart

## 4. SLA Expectations

| Metric | Requirement |
|--------|-------------|
| Latency (p95) | < 500ms for single customer lookup |
| Latency (p95) | < 2s for batch (up to 200 customers) |
| Availability | 99.5% (degrade gracefully if BSS is down) |
| Error rate | < 0.1% |

**Degradation behaviour**: If BSS is unreachable, return `RevenueResult` with `total_revenue_at_risk=None`, `is_estimate=True`, `requires_manual_valuation=True`.

## 5. Data Sensitivity

- Customer billing data is **PII** and subject to GDPR
- Adapter MUST NOT log `monthly_fee` values at INFO level
- All BSS responses must be scrubbed by `pii_scrubber.py` before inclusion in audit trails
- Retention: BSS query results are ephemeral; only aggregated `revenue_at_risk` is persisted

## 6. Current Adapters

| Adapter | Class | Status | `is_estimate` |
|---------|-------|--------|---------------|
| Local SQLAlchemy | `LocalBSSAdapter` | Production-ready | `False` |
| Mock (CI/testing) | `MockBSSAdapter` | In-memory only | `True` |
| Amdocs | `AmdocsBSSAdapter` | Planned | `False` |
| Cerillion | `CerillionBSSAdapter` | Planned | `False` |
| CSG | `CSGBSSAdapter` | Planned | `False` |

## 7. Adding a New Adapter

1. Create `backend/app/services/bss_adapters/<vendor>_adapter.py`
2. Subclass `BSSAdapter` from `bss_adapter.py`
3. Implement all three required methods
4. Set `is_estimate=False` and `source="<vendor_name>"` in `RevenueResult`
5. Add integration tests in `tests/integration/test_bss_<vendor>.py`
6. Register in adapter factory (config-driven selection)
