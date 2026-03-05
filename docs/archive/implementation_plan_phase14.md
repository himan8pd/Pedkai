# Phase 14: Customer Experience Intelligence — Implementation Plan

## Goal
Implement the third strategic pillar (CX Intelligence) by correlating real-time network anomalies with customer churn risk, enabling "Proactive Care" automation.

## Proposed Changes

### [NEW] [customer_orm.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/models/customer_orm.py)
ORM models for Customer identity and churn risk.
- `CustomerORM`: `id`, `external_id`, `churn_risk_score` (0.0 - 1.0), `associated_site_id` (to link with anomalies).
- `ProactiveCareORM`: Records of triggered notifications.

### [NEW] [cx_intelligence.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/cx_intelligence.py)
Service to correlate anomalies with at-risk customers.
- `identify_impacted_customers(anomaly_id)`: Finds customers associated with the site experiencing an anomaly who have a churn risk > 0.7.
- `trigger_proactive_care(impacted_customers)`: Mocks the sending of notifications.

### [NEW] [cx_router.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/api/cx_router.py)
API endpoints for CX intelligence.
- `GET /api/v1/cx/impact/{anomaly_id}`: List high-risk customers impacted by an event.
- `POST /api/v1/cx/proactive-care/simulate`: Trigger the care automation flow.

## Verification Plan

### Automated Tests
- `pytest tests/unit/test_cx_intelligence.py`
- Verify correlation logic pulls the correct high-risk customers for a given site ID.

### Manual Verification
1. Create a "Critical" alarm for `Site-A`.
2. Call `/api/v1/cx/impact/{alarm_id}`.
3. Verify that customers regularily using `Site-A` with high churn scores are returned.
4. Trigger simulation and verify `ProactiveCareORM` records are created.
