# BSS Integration Implementation Plan

This plan details the integration of the BSS Data Layer (Revenue & Billing) into the `LLMService` to provide real business context for policy decisions.

## Proposed Changes

### [Backend]

#### [MODIFY] [llm_service.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My Drive/AI Learning/AntiGravity/Pedkai/backend/app/services/llm_service.py)
- Update `generate_explanation` to accept an `AsyncSession`.
- Integrate `BSSService` to calculate real `predicted_revenue_loss`.
- Resolve `customer_tier` from actual billing accounts rather than name-based heuristics.

#### [MODIFY] [cx_intelligence.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My Drive/AI Learning/AntiGravity/Pedkai/backend/app/services/cx_intelligence.py)
- Update search logic to return customer IDs and tiers for inclusion in the incident context.

## Verification Plan

### Automated Tests
- Run `scripts/verify_strategy_v2.py` (updated to provide a DB session) to confirm that the Policy Engine receives and acts upon real BSS data.
- Confirm SITREP output displays correct "POLICY APPLIED" markers based on real revenue thresholds.
