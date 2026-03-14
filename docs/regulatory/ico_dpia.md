# Data Protection Impact Assessment (DPIA)

**Document Reference:** PEDKAI-REG-002
**Date:** March 2026
**Data Controller:** [Operator Name — customer of Pedk.ai Ltd]
**Data Processor:** Pedk.ai Ltd
**DPO Review Status:** Pending
**UK GDPR Article 35 Necessity:** Required — automated processing of operator network data at scale

---

## 1. Description of Processing

### 1.1 What data is processed?

Pedk.ai processes the following categories of data in the course of providing AI-assisted network operations and reconciliation services to telecoms operators:

**Network telemetry and performance data.** Cell-level key performance indicators (KPIs) including Physical Resource Block (PRB) utilisation, Signal-to-Interference-plus-Noise Ratio (SINR), downlink and uplink throughput, handover success rates, and Radio Link Failure (RLF) counts. These are aggregate measurements reflecting the collective behaviour of all user equipment attached to a given cell at a given sampling interval. No individual subscriber's device-level metrics are ingested. Alarm events (alarm identifier, entity identifier, severity, specific problem code, alarm raising timestamp, and clearing timestamp) are ingested via TMF642-compliant Kafka streams.

**CMDB entity records.** Configuration Item (CI) attributes as exported from the operator's Configuration Management Database: vendor, hardware model, software version, site identifier, geographic coordinates (cell sector level, not subscriber location), and declared logical relationships between CIs. These records describe physical network equipment, not natural persons.

**ITSM ticket data (Offline PoC and Advisory Mode only).** Incident and change ticket text, including resolution notes. These may incidentally contain operator staff identifiers (e.g., engineer usernames or employee IDs embedded in ticket bodies) where an engineer has documented their own troubleshooting activity.

**Decision Feedback data.** Where operators interact with AI-generated recommendations via the NOC dashboard, the `DecisionFeedbackORM` table records a per-operator vote (accept/reject/override) linked to an `operator_id` field. This `operator_id` is a pseudonymous internal identifier tied to the operator's authenticated session.

**What is not processed.** No end-user personal data (subscriber names, MSISDNs, IMSIs, IMEIs, or home addresses) is ingested into Pedk.ai at any deployment stage prior to full BSS integration (which is explicitly deferred to a future roadmap milestone, per the product's Trust Architecture). Cell-level KPI aggregates cannot be disaggregated to identify any individual subscriber's behaviour.

### 1.2 Data flow

Telemetry is ingested via Apache Kafka streams sourced from the operator's Operations Support System (OSS). Alarm events arrive over the same transport layer. On ingestion, data is normalised by a vendor-specific Alarm Normaliser layer and written to:

- **TimescaleDB** (hot/warm tier): time-series KPI samples and alarm events, retained for 30–90 days by default, subject to the operator's configured retention policy.
- **PostgreSQL with JSONB** (decision store): decision traces, topology graph data, AI-generated recommendations, and operator feedback records. Decision traces are retained per operator's configured policy; the default retention for KPI data is 90 days. Decision traces containing the analytical reasoning behind a recommendation are retained indefinitely unless the operator exercises their right to erasure.

The system is multi-tenant by design. Every database table carries a `tenant_id` column. Every query is scoped by `tenant_id` at the application layer. There is no cross-tenant analytics capability, no aggregated view across tenants, and no mechanism by which one operator's data can be accessed from another operator's session. Tenant data boundary is enforced both at the ORM layer and at the API layer.

Where AI-generated Situation Reports (SITREPs) are produced using an external Large Language Model (LLM) provider, all data is passed through a PII scrubbing pipeline (`pii_scrubber.py`) before transmission. The scrubber detects and replaces phone numbers, IMSI, IMEI, email addresses, IP addresses, and account identifiers. A scrub manifest (containing the field type, a hash of the original value, and the replacement token — but not the original value itself) is logged for 90 days for audit purposes. The scrub manifest contains no personal data.

Data transfers to external LLM providers (currently Google Gemini API) are governed by Standard Contractual Clauses (SCCs). No personal data is transmitted to external providers; only scrubbed operational prompts are sent.

### 1.3 Data subjects and categories

The predominant data subjects in Pedk.ai's processing are **network equipment entities**, not natural persons. CMDB records describe hardware assets; telemetry describes their aggregate traffic behaviour.

However, two categories of natural persons are identified as data subjects:

1. **Operator staff (NOC engineers and administrators).** Where operator staff usernames or employee identifiers appear in ITSM ticket resolution notes, or are recorded via the `DecisionFeedbackORM.operator_id` field when providing feedback on AI recommendations, this constitutes personal data of employees. The `operator_id` is a pseudonymous identifier — it does not directly contain a name, but can be linked back to a named individual within the operator's identity management system.

2. **Future: telecoms end-users (subscribers).** At Day 1 and Shadow Mode deployments, no subscriber personal data is processed. If and when BSS integration proceeds (planned for Month 12+ of the trust progression), subscriber data will become in scope and this DPIA must be updated to cover that expanded processing before integration is activated.

---

## 2. Necessity and Proportionality

### 2.1 Necessity

Real-time network anomaly detection requires continuous ingestion of KPI time-series data. There is no technically feasible alternative to processing cell-level telemetry if the purpose is to detect sleeping cells, KPI drift, and cross-domain causal root causes. The processing is essential to the core product function.

ITSM correlation requires some form of attribution to understand the human decision-making context that surrounds a network event. Operator feedback attribution (the `operator_id` field) enables the system to learn from expert judgement. Without this attribution, the system cannot improve its recommendations over time, nor can it surface the "tribal knowledge" component of the Dark Graph reconciliation that is central to the product's value proposition.

CMDB entity data processing is necessary to compute divergence between declared network topology and observed network behaviour. No less-invasive approach can achieve this purpose.

### 2.2 Proportionality

Processing is proportionate. The following data minimisation measures are in place:

- Subscriber data is aggregated at source (within the operator's OSS) before reaching Pedk.ai. No IMSI, MSISDN, IMEI, or other subscriber identifier enters the system under standard deployment.
- The `operator_id` field is pseudonymous. Pedk.ai holds the pseudonym; the operator's identity management system holds the key.
- ITSM ticket text is processed for semantic relationship extraction only, not retained in full as a searchable corpus of employee activity.
- External LLM calls are subject to mandatory PII scrubbing. The scrub manifest retains only a one-way hash of the original value.
- Cold-tier data (Parquet / S3) is retained at operator discretion, with a default retention ceiling of seven years for regulatory compliance (Ofcom, Communications Act 2003), and a right-to-erasure pathway for any personal data within it.

---

## 3. Risk Assessment

| Risk | Likelihood | Impact | Residual Risk | Mitigation |
|------|-----------|--------|---------------|------------|
| Unauthorised access to decision traces containing operator_id data | Low | Medium | Low | JWT authentication, hierarchical RBAC (Admin / Operator / Viewer), TLS in transit, non-root container execution |
| Cross-tenant data leakage | Very Low | High | Very Low | Mandatory `tenant_id` scoping enforced at ORM and API layers; no cross-tenant API surface exists |
| Re-identification of subscribers from cell-level KPI aggregates | Very Low | High | Very Low | Only cell-level aggregates are processed; no IMSI, MSISDN, or device identifier is ingested; disaggregation to individual subscriber level is technically infeasible from the data Pedk.ai holds |
| Operator staff personal data processed without adequate lawful basis | Low | Low | Very Low | `operator_id` is pseudonymous; processing is on Legitimate Interests basis (network operations accountability); operator's employment relationship establishes reasonable expectation of activity logging |
| PII leakage to external LLM provider via unscrubbed prompt | Low | High | Low | Mandatory PII scrubbing pipeline applied to all LLM API calls; scrub manifest logged for audit; scrubber covers phone numbers, IMSI, IMEI, email, IP addresses, account identifiers |
| Data breach exposing network topology data | Low | Medium | Low | Data held within operator-controlled infrastructure under customer-hosted deployment model; Pedk.ai does not operate a shared cloud store for operator data; TLS at rest and in transit |
| Operator staff data retained beyond necessity | Low | Low | Very Low | Operator configures retention policy; default 90-day KPI retention; deletion API provided for erasure requests; audit trail retention follows operator's regulatory obligations |
| International transfer of personal data to LLM provider without adequate safeguard | Low | Medium | Very Low | SCCs in place with Google (Gemini API); only scrubbed, non-personal data transmitted; no raw personal data crosses the API boundary |

---

## 4. Lawful Basis

Processing of network telemetry, CMDB data, and alarm events is carried out under **Article 6(1)(f) of the UK GDPR (retained EU law) — Legitimate Interests** of the data controller (the operator). The legitimate interest is the optimisation, assurance, and security management of a critical national communications network. The balancing test is satisfied:

- The operator has a genuine, pressing interest in network quality, fault identification, and service assurance.
- Processing is limited to what is necessary for those purposes; no extraneous personal data is collected.
- Processing of operator staff data (`operator_id`) is also on a Legitimate Interests basis. Staff members working in an operational environment have a reasonable expectation that their actions on production systems are attributable and auditable. The processing is limited to pseudonymous identifiers, not behavioural profiles.

For audit trail logging (usernames, timestamps, action records), the lawful basis is also **Article 6(1)(f)**, with the further support of **Article 6(1)(c) (legal obligation)** where Ofcom-regulated operators are required under the Communications Act 2003 and associated directions to maintain records of network operations.

For any future processing of subscriber personal data beyond aggregate KPIs — including any direct engagement with subscriber accounts via BSS integration — the lawful basis would need to be assessed afresh. Depending on the processing activity, the appropriate basis would be **Article 6(1)(b) (contract performance)** between the operator and their subscriber, or **Article 6(1)(a) (consent)** for any proactive outreach. No such processing is in scope under this DPIA. A revised DPIA is required before BSS integration is activated.

---

## 5. Rights of Data Subjects

**Operator staff (bearing pseudonymous operator_id records):**

| Right | Implementation |
|-------|---------------|
| Right of access (Art. 15) | The operator (as data controller) handles access requests from their own staff. Pedk.ai provides an administrative API to export all records associated with a given `operator_id` to support the operator's fulfilment of access requests. |
| Right to rectification (Art. 16) | Operator updates the `operator_id` mapping in their identity system; Pedk.ai records referencing the pseudonym are unaffected as they contain no name data. |
| Right to erasure (Art. 17) | Pedk.ai provides a deletion API (`DELETE /api/v1/admin/operators/{operator_id}/data`). Decision feedback records are pseudonymised; full erasure is available subject to the operator's regulatory retention obligations for audit trails. Where a 7-year retention obligation applies (Ofcom), records are anonymised rather than deleted during the retention window. |
| Right to object (Art. 21) | Applicable where processing is on Legitimate Interests basis. Operator's DPO handles objection requests. Where an individual staff member's objection is upheld, their `operator_id` data is pseudonymised to the point of effective anonymisation. |
| Rights regarding automated decision-making (Art. 22) | Pedk.ai generates AI-assisted recommendations and SITREPs. No automated decision producing legal or similarly significant effects on a natural person is made without human review. The system is classified as Advisory Mode by default; all recommendations require operator acceptance before action is taken. Article 22 is therefore not engaged in normal operation. |

---

## 6. DPO Consultation

This DPIA has been prepared by the Pedk.ai engineering and product team in advance of DPO review. The following items require DPO attention before production deployment is approved:

1. **Adequacy of PII scrubbing for external LLM API calls.** The DPO should satisfy themselves that the `pii_scrubber.py` implementation provides sufficient technical assurance that no personal data transits to external providers, and that the scrub manifest logging arrangement is consistent with the operator's data processing agreements.

2. **Retention periods for operator staff audit trails.** The default indefinite retention of decision traces should be reviewed against the proportionality principle. The DPO should confirm that the operator's configured retention policy is lawful under the UK GDPR storage limitation principle (Article 5(1)(e)), and that a default upper bound is set.

3. **Cross-border data transfer mechanism for LLM providers.** The DPO should confirm that SCCs with Google (Gemini API) are current and have been reviewed following the UK ICO's International Data Transfer Agreement (IDTA) or UK Addendum to EU SCCs framework, as applicable under post-Brexit UK data transfer rules.

4. **Trigger conditions for DPIA refresh.** The DPO should agree the conditions under which this DPIA must be revised — in particular, confirming that BSS integration (subscriber personal data) mandates a fresh DPIA before any deployment.

**Condition for pilot deployment:** No deployment to a production operator environment is permitted until DPO sign-off is confirmed in writing. This condition is non-negotiable.

---

## 7. Outcome and Sign-off

This DPIA identifies no processing that carries a high residual risk to the rights and freedoms of natural persons that would require prior consultation with the ICO under Article 36 of the UK GDPR. The primary data subjects (operator staff) are affected only via pseudonymous identifiers in an employment context where such processing is proportionate and expected. Subscriber personal data is out of scope at current deployment stages.

Subject to:
- DPO sign-off as detailed in Section 6, and
- the operator conducting its own DPIA covering their deployment context (as data controller),

Pedk.ai considers processing under this DPIA to be lawful, necessary, and proportionate.

**Review date:** Six months after pilot go-live, or earlier upon any material change to the processing (including BSS integration activation, change of LLM provider, or change in deployment model from customer-hosted to Pedk.ai-hosted cloud).

---

*This document is prepared under UK GDPR (as retained in UK law by the European Union (Withdrawal) Act 2018 and the Data Protection Act 2018). References to "GDPR" and "UK GDPR" throughout this document refer to that retained legislation.*

*Prepared by: Pedk.ai Ltd Engineering and Product Team*
*DPO Review: Pending*
*Document Reference: PEDKAI-REG-002*
