# Pedkai — Data Protection Impact Assessment (ICO DPIA)

**Document ID**: PEDKAI-DPIA-001
**Version**: 1.0
**Classification**: Confidential — Legal
**Date**: 2026-02-25
**DPO Review**: Pending
**Legal Basis**: GDPR Article 35 — High-risk processing

---

## 1. Processing Description

### 1.1 Nature of Processing

Pedkai processes the following data categories in the course of AI-assisted network operations:

| Data Category | Examples | Lawful Basis | Retention |
|--------------|---------|--------------|-----------|
| Network telemetry | KPIs, alarms, topology | Legitimate interest | 90 days |
| Customer billing data | Monthly fee, plan name, disputes | Contract performance | Session-only (not persisted) |
| Operator identity | Username, email, actions taken | Legitimate interest | Audit trail: 2 years |
| AI-generated content | SITREPs, recommendations | N/A (not personal data) | 90 days |

### 1.2 Purpose of Processing

- Correlate network alarms to reduce operator cognitive load
- Detect sleeping cells and KPI drift for preventive maintenance
- Calculate revenue-at-risk for impacted customers (aggregated, not individual)
- Generate incident explanations using AI (Gemini LLM)

### 1.3 Data Subjects

- **Network operators**: Authenticated users whose actions are audit-logged
- **Customers**: Identified by internal UUID; billing data used for aggregate revenue calculations only. No direct customer communication is performed by Pedkai.

## 2. Necessity and Proportionality

### 2.1 Necessity

Processing of network telemetry is essential for network operations. Customer billing data processing is limited to aggregate revenue-at-risk calculations required for incident prioritisation.

### 2.2 Proportionality

- Customer billing queries return aggregated revenue figures, not individual account details
- PII is scrubbed from all data sent to external AI providers (`pii_scrubber.py`)
- Sovereign tenants have egress controls preventing data from leaving the operator's network
- Billing query results are ephemeral — only aggregated `revenue_at_risk` is persisted

## 3. Risk Assessment

| Risk | Likelihood | Severity | Residual Risk | Mitigation |
|------|-----------|----------|---------------|------------|
| Unauthorised access to billing data | Low | High | Low | OAuth2 + tenant isolation |
| PII leakage to external LLM | Medium | High | Low | PII scrubbing before API calls |
| Cross-tenant data exposure | Very Low | Critical | Very Low | Mandatory tenant_id filters |
| AI profiling of individuals | N/A | N/A | N/A | No individual profiling performed |
| Data subject rights (erasure) | Low | Medium | Low | BSS data is ephemeral; audit logs have retention policy |

## 4. Data Subject Rights

| Right | Implementation |
|-------|---------------|
| Access (Art. 15) | Operator identity data available via admin panel |
| Erasure (Art. 17) | Audit logs subject to 2-year retention; BSS data is ephemeral |
| Portability (Art. 20) | Not applicable — no customer personal data is stored |
| Objection (Art. 21) | AI recommendations are advisory; operators can disable AI features |
| Automated decisions (Art. 22) | No fully automated decisions affecting data subjects |

## 5. Technical and Organisational Measures

- Encryption at rest (database) and in transit (TLS)
- OAuth2 authentication with role-based access control
- Tenant isolation enforced at database query level
- Structured JSON logging with correlation IDs for forensic analysis
- PII scrubbing on all external API calls
- Sovereignty module for data residency enforcement

## 6. DPO Consultation

This DPIA requires review and sign-off by the Data Protection Officer before production deployment. Key areas requiring DPO attention:

1. Adequacy of PII scrubbing for LLM API calls
2. Retention period for operator audit trails (currently 2 years)
3. Cross-border data transfer implications if using cloud-hosted LLM providers
