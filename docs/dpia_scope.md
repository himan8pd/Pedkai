# DPIA Scoping Document — Pedkai AI Network Operations System

**Version**: 1.0 | **Prepared by**: Pedkai Engineering | **Date**: February 2026  
**Review required by**: DPO, Legal Counsel, Regulatory Affairs

> [!CAUTION]
> This document requires formal DPO sign-off before the pilot deployment. Do not deploy to production without a completed and signed DPIA.

---

## 1. Data Categories Processed

| Category | Examples | Classification |
|----------|----------|----------------|
| Network KPIs | PRB utilisation, data volume, RSRQ, CQI | Operational — not personal |
| Alarm events | Alarm ID, entity ID, severity, timestamp, specific problem | Operational — may link to location |
| Customer identifiers | Account IDs, hashed MSISDNs, BSS IDs | **Personal data** (pseudonymised) |
| Billing amounts | Monthly fee, service plan type | **Personal data** (financial) |
| Location data | Cell site IDs, geographic coordinates | **Personal data** (location — cell-level granularity) |
| LLM prompts (post-scrubbing) | Scrubbed prompts sent to Gemini API | Non-personal (PII removed by `PIIScrubber`) |
| Audit trails | User ID, action, timestamp, tenant_id | Operational — personal in context of user identity |

---

## 2. Lawful Basis

| Processing Activity | Lawful Basis | Article |
|---------------------|-------------|---------|
| Network fault detection and correlation | Legitimate interests (network operations) | Art. 6(1)(f) |
| SLA management and customer impact assessment | Contractual necessity | Art. 6(1)(b) |
| Emergency service notifications | Legal obligation | Art. 6(1)(c) |
| Proactive customer communications | Explicit consent (opt-in) | Art. 6(1)(a) |
| Audit trail logging | Legitimate interests (security, accountability) | Art. 6(1)(f) |

---

## 3. Retention Policies

| Data Type | Retention Period | Basis |
|-----------|-----------------|-------|
| KPI data (TimescaleDB) | **30 days rolling** | Operational necessity |
| Alarm events | **30 days rolling** | Operational necessity |
| LLM prompts (scrubbed, logged) | **90 days** | Audit traceability |
| Incidents | **7 years** | Regulatory obligation (Ofcom, Communications Act 2003) |
| Audit trails | **7 years** | Regulatory obligation |
| Decision memory | **Indefinite** (with right-to-erasure pathway) | Operational — see §5 below |
| User accounts | Until account deletion + 30 days | Contractual |

---

## 4. Right-to-Erasure Pathway

Customer data is stored in the `customers` table with `customer_id` as the primary key. Decision memory records reference `customer_id` but do not contain name, MSISDN, or contact details directly.

**Erasure procedure**:
1. Anonymise customer record: set `msisdn_hash = NULL`, `name = '[REDACTED]'`, `email = NULL`
2. Decision memory records referencing the customer_id remain but contain no PII
3. Billing records are retained for 7 years (regulatory) but anonymised
4. Confirm erasure with DPO within 30 days of request (GDPR Art. 17)

**Limitation**: Incident records referencing the customer cannot be erased for 7 years due to regulatory obligation. This limitation is disclosed to data subjects.

---

## 5. EU AI Act Risk Categorisation

Pedkai is classified as a **high-risk AI system** under **Annex III, Point 2** of the EU AI Act (AI systems used in critical infrastructure management).

**Required obligations**:

| Obligation | Status | Owner |
|------------|--------|-------|
| Conformity assessment | ⏳ Required before production | Engineering + Legal |
| Technical documentation (Art. 11) | This plan + `agentic_development_plan_v2.md` | Engineering |
| Human oversight measures (Art. 14) | ✅ 3 mandatory human gates implemented | Engineering |
| Accuracy and robustness metrics | ⏳ Requires shadow-mode period | Engineering |
| Registration in EU database | ⏳ Required before EU deployment | Legal |
| Post-market monitoring plan | ⏳ Required before production | Engineering |

**Accuracy metrics to be established via shadow mode** (see `docs/shadow_mode.md`):
- False positive rate (target: < 5%)
- Missed correlation rate (target: < 10%)
- MTTR improvement (target: > 15% vs baseline)

---

## 6. PII Scrubbing Confirmation

All data sent to external LLMs (Google Gemini API) is processed by `backend/app/services/pii_scrubber.py` before transmission. The scrubber:

1. Detects and replaces: phone numbers, IMSI, IMEI, email addresses, IP addresses, account IDs
2. Returns a **scrub manifest** containing: `{field_type, original_value_hash, replacement}` — the manifest does NOT contain original PII values
3. The scrub manifest is logged for 90 days for audit purposes
4. Prompt content after scrubbing is verified to contain no recognisable PII patterns

Retention of scrub manifests: 90 days (sufficient for regulatory audit; contains no personal data).

---

## 7. Third-Party Data Transfers

| Recipient | Data Transferred | Legal Mechanism | Country |
|-----------|-----------------|-----------------|---------|
| Google (Gemini API) | Scrubbed LLM prompts only | Standard Contractual Clauses | USA (EU SCCs required) |
| No other third parties | — | — | — |

> [!IMPORTANT]
> Google Gemini API data processing agreement must be in place before production deployment. Confirm with Legal Counsel.
