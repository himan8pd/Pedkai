# Pedk.ai — Product Overview

**AI-Native Operational Reconciliation Engine**

---

## The Problem Every Operator Faces

Every large telecommunications network has a blind spot. The physical reality of infrastructure — what's actually running, how it's connected, where traffic actually flows — is structurally out of sync with the documented intent — CMDBs, change tickets, architecture diagrams. This gap grows silently, year after year.

The result: engineers spend hours diagnosing root causes because the topology map they're working from is wrong. Hardware gets swapped in the field but never updated in the CMDB. Dependencies exist that no document records. Decommissioned assets continue to consume licence fees because nobody knows they're still listed.

We call this divergence the **Dark Graph**. It exists in every operator. And while nobody in the C-suite wakes up worrying about CMDB accuracy, they do worry about what CMDB inaccuracy *causes*. 

### The Bottom Line

Pedk.ai translates technical reconciliation into four hard executive value levers:

| Executive Pain Point | Business Impact | Pedk.ai's Answer |
|----------------------|-----------------|------------------|
| **The "Integration Tax" (OPEX)** | Operators spend millions annually on L2/L3 engineers blindly hunting for root causes because their maps are wrong. This is dead OPEX. | By eliminating the Dark Graph, troubleshooting goes from "hunting in the dark" to "following a lit path", dropping MTTR and structural OPEX. |
| **Silent Revenue Leakage** | Sleeping cells report as "healthy" but serve zero traffic. Customers churn; SLAs are breached; revenue leaks silently. | Pedk.ai finds the failures that traditional element managers and alarms miss entirely, safeguarding top-line revenue. |
| **Phantom CapEx / Licences** | Decommissioned but fully-licenced instances (Phantom Nodes) cost real money in software renewals and vendor maintenance. | Pedk.ai identifies assets generating zero telemetry for months, enabling immediate licence clawbacks and hard savings. |
| **Headline / Brand Risk** | Major outages happen because an undocumented dependency cascaded unexpectedly. Brand damage is severe. | Continuous reconciliation makes network brittleness visible *before* the critical collapse occurs. |

---

## What Pedk.ai Does

Pedk.ai is an intelligence fabric that sits between your existing systems — element managers, ITSM platforms, CMDBs — and tells you the truth about your network. It cross-correlates what your network *actually does* (telemetry) against what your organisation *thinks* it does (CMDB) and what your engineers *actually know* (ticket resolution patterns).

Pedk.ai **augments** your existing tools. It does not replace your element managers, your ITSM platform, or your CMDB. They do what they're designed to do. Pedk.ai adds the reconciliation layer they've never had.

---

## How It Works — Day 1

Pedk.ai requires no production access on Day 1. No write access to any system. No sensitive data.

You provide three read-only historical datasets:

| What You Share | What It Contains | What Pedk.ai Finds |
|----------------|------------------|-------------------|
| **CMDB Snapshot** | Your Configuration Items and their declared relationships | The "documented truth" — what you think the network looks like |
| **Telemetry History** | 12 months of PM counters, event logs, alarm records | The "physical truth" — what the network actually did |
| **Ticket Archive** | Incident and change ticket history | The "human truth" — how your engineers actually fix problems |

Within 48 hours, Pedk.ai delivers a **Divergence Report**:

- Entities generating telemetry with no CMDB record (**undocumented infrastructure**)
- CMDB records with zero telemetry for months (**phantom assets** consuming licence fees)
- Hardware swaps detected from telemetry/CMDB mismatches (**identity mutations**)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns

**Zero risk. Zero disruption. Proven value before any deeper conversation.**

---

## Core Capabilities

### Dark Graph Reconciliation

Pedk.ai's foundational capability. Discovers the six types of divergence between network reality and documented intent:

- **Undocumented entities** — infrastructure that exists but isn't in the CMDB
- **Phantom assets** — CMDB entries for infrastructure that no longer exists or functions
- **Undocumented connections** — real dependencies between systems that no document records
- **Phantom connections** — documented links that carry no traffic
- **Attribute drift** — parameters that have been changed in the field but never updated
- **Identity mutations** — hardware swaps where the function persists but the physical entity has changed

### Abeyance Memory

Pedk.ai's unique differentiator. Traditional monitoring processes events in real-time and discards what it can't resolve. Pedk.ai does not discard. It remembers.

Unresolved technical fragments — a CLI output pasted into a ticket note, a transient telemetry anomaly, a reference to an unknown IP address — are held in persistent semantic storage. Days, weeks, or months later, when a new piece of evidence arrives that matches, Pedk.ai **connects the dots** across time and across data types.

No competing product does this. Active discovery scanners see only what's present when they scan. Rule-based engines need a rule for every pattern. Abeyance Memory is patient. It finds connections that no human analyst could spot across thousands of tickets and millions of events.

### Sleeping Cell Detection

Sleeping cells are silent failures — a cell reports "healthy" to the element manager but serves zero users. No alarms fire. The gap itself is the signal.

Pedk.ai detects sleeping cells through multiple complementary methods:

- **Baseline comparison** — flagging cells with zero traffic when historical patterns predict activity
- **Neighbour analysis** — identifying cells performing significantly worse than their geographic neighbours
- **Correlation monitoring** — detecting when KPI relationships that should move together suddenly decouple
- **Multi-dimensional pattern recognition** — identifying complex degradation patterns that no single threshold would catch
- **UE measurement analysis** — comparing device-reported signal quality against cell-reported status
- **Handover pattern analysis** — detecting asymmetric handover behaviour indicating silent failures

### Customer Experience Intelligence

Every telco predicts churn. Pedk.ai does something different: it connects **network root causes** to **individual customer impact**.

By correlating cell-level performance with subscriber connection patterns, Pedk.ai constructs a per-subscriber Quality of Experience score spanning coverage, data throughput, voice quality, service availability, and connection stability. When scores decline for a cluster of subscribers, Pedk.ai identifies both the affected customers and the network fault causing the degradation — enabling proactive care before customers complain.

### Autonomous Network Operations

Pedk.ai provides NOC teams with AI-generated situational reports (SITREPs) that explain anomalies in plain language, identify root causes through graph-based analysis, and recommend actions. Support for multi-service anomaly detection across mobile, voice, SMS, and landline services, with congestion management and emergency compliance monitoring.

### AI-Driven Capacity Planning

Data-driven network densification recommendations based on real KPI hotspots, with CapEx optimisation within budget constraints.

---

## Operator Control — Always

Pedk.ai's autonomy is a spectrum. You choose your comfort level:

| Level | What Pedk.ai Does | What You Do |
|:-----:|------------------|-------------|
| **Advisory** | Generates reports and recommendations. Takes zero action. | Full manual control. |
| **Assisted** | Creates draft tickets with pre-populated fields. | You review and dispatch every ticket. |
| **Supervised** | Executes routine actions with an override window. | You can veto any action before it takes effect. |
| **Gated** | Executes approved action types with safety gates. | You review the audit trail. Kill-switch available. |

**Default: Advisory.** You advance only when you're ready.

Pedk.ai learns from what your operators actually do — not just button clicks, but real operational actions. When Pedk.ai recommends an action and your operator takes a different one, that delta is the learning signal that makes Pedk.ai smarter over time.

---

## Trust Progression

| Timeline | What Happens | Your Risk |
|----------|-------------|-----------|
| **Day 1** | Offline analysis of historical data. Divergence Report delivered. | None. Read-only. No production access. |
| **Month 3** | Shadow mode alongside existing tools. Accuracy validated. | None. Read-only production feeds. |
| **Month 6** | Advisory mode. SITREPs generated for NOC team. | None. Advisory only. No automated actions. |
| **Month 12+** | Deeper integration discussed only after proven value. | Earned trust. You decide the pace. |

---

## Standards & Compliance

- **TM Forum**: TMF642 Alarm Management API, TMF628 Performance Management API
- **Multi-vendor**: Ericsson (XML), Nokia (JSON), SNMP — normalised into unified internal format
- **Security**: JWT authentication, hierarchical RBAC, tenant data isolation, GDPR consent enforcement, data sovereignty controls
- **Multi-tenancy**: Full tenant isolation — every data table scoped by tenant, no cross-tenant access
- **LLM**: Vendor-neutral — supports cloud-hosted and on-premises models for data sovereignty requirements

---

## Deployment

Pedk.ai deploys on Kubernetes with Docker containers. Cloud-hosted SaaS or on-premises. Supports PostgreSQL with TimescaleDB for time-series analytics, Apache Kafka for telemetry streaming, and vector search for semantic intelligence.

No heavyweight infrastructure requirements. No rip-and-replace migration. Pedk.ai operates alongside your existing stack from Day 1.

---

## Quality Process

Pedk.ai has been subjected to a rigorous multi-phase review cycle:

- **Three-pass technical audit**: forensic code review, architecture viability assessment, and adversarial red-team review
- **Five-member executive committee**: spanning operations, strategy, engineering, QA, and executive leadership
- **Formal remediation cycle**: structured gap analysis with tracked resolution
- **Erdos AI methodology**: independent assessment using the Erdos Enterprise AI Deployment Framework, covering product readiness, business case integration, and workforce readiness

This is not a prototype presented as a product. It is an engineered system that has been systematically challenged, found wanting in specific areas, and improved through structured remediation.

---

## Evidence-Based Approach

Pedk.ai uses pluggable mathematical frameworks for evidence fusion — selecting the optimal approach based on your data landscape. Customers with rich telemetry streams benefit from one methodology; those with sparse, policy-gated environments benefit from another.

Causal inference uses established statistical methods for time-series analysis, with a roadmap to incorporate more advanced techniques for non-linear and multi-variable causality as they mature.

The approach is configurable per deployment. No one-size-fits-all.

---

## The Conversation Pedk.ai Enables

Pedk.ai doesn't ask you to trust it. It asks you to **test it**.

Share historical data. Get a Divergence Report. If it finds value, continue the conversation. If it doesn't, you've lost nothing.

The question isn't whether your CMDB has gaps. It does. Every CMDB does. The question is whether you want to know what they are.

---

*Pedk.ai — AI-Native Operational Reconciliation Engine*  
*Intelligence fabric for enterprise network operations*
