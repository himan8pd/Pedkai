# DPIA Scope: Pedkai Project

Data Protection Impact Assessment (DPIA) summary for the Pedkai project.

## 1. Project Overview
Pedkai is an autonomous network management agent designed to automate NOC operations while maintaining human oversight.

## 2. Personal Data Involved
- **Customer Identifiers**: Hashed MSISDNs / Account IDs (Internal BSS IDs).
- **Location Data**: Associated Site IDs (Cell level granularity).
- **Usage Metrics**: PRB utilization, data volume, churn risk scores.

## 3. Data Processing Activities
- **Impact Analysis**: Linking network faults to specifically impacted customers.
- **Proactive Comms**: Sending automated SMS/Email alerts to customers.
- **Governance**: User access logging for the NOC dashboard.

## 4. Risks & Mitigations
- **Privacy Leakage**: Mitigated by strict multi-tenant isolation and data hashing.
- **Unwanted Comms**: Mitigated by mandatory "Consent = False" default and opt-in checking.
- **Unauthorized Access**: Mitigated by RBAC and JWT-based authentication.

## 5. Compliance Status
- GDPR / Data Protection Act 2018 compliant.
- Consent management enforced at the API layer.
