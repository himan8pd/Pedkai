---
# 1. Document Identity
title: |
  \fontsize{30}{35}\selectfont pedk.ai - AI-native operational reconciliation engine
subtitle: "Version 2.0"
author: |
  \fontsize{20}{22}\selectfont Himanshu Thakur
date: |
  \fontsize{16}{16}\selectfont 01-Apr-2026
subject: "Product Specification"
keywords: [Dark Graph, Abeyance Memory, pedk.ai]
lang: "en"

# 5. Layout & LaTeX Fixes + Fonts
geometry: "margin=2.5cm"
header-includes: |
  \makeatletter
  \def\headrulewidth{0pt}
  \def\footrulewidth{0pt}
  \usepackage{anyfontsize}
  \makeatother

  \usepackage{fontspec}

  \setmainfont[
    Ligatures      = TeX,
    BoldFont       = {Inter Bold},
    ItalicFont     = {Inter Italic},
    BoldItalicFont = {Inter Bold Italic}
  ]{Inter}

  \setmonofont{Courier New}

# 3. Header & Footer
header-left: "pedk.ai - Product Specification"
header-right: "01-Apr-2026"
footer-left: "Confidential"
footer-right: "Page \\thepage"

# 4. Title Page Styling (Eisvogel)
titlepage: true
titlepage-color: "06203b"
titlepage-text-color: "FFFFFF"
titlepage-rule-height: 0
titlepage-logo: "pedk.ai.jpeg"
logo-width: "280pt"
---
# pedk.ai — Product Overview

**AI-Native Operational Reconciliation Engine**

## The Problem Every Operator Faces

Every large telecommunications network has a blind spot. The physical reality of infrastructure — what's actually running, how it's connected, where traffic actually flows — is structurally out of sync with the documented intent — CMDBs, change tickets, architecture diagrams. This gap grows silently, year after year.

The result: engineers spend hours diagnosing root causes because the topology map they're working from is wrong. Hardware gets swapped in the field but never updated in the CMDB. Dependencies exist that no document records. Decommissioned assets continue to consume licence fees because nobody knows they're still listed.

We call this divergence the **Dark Graph**. It exists in every operator. And while nobody in the C-suite wakes up worrying about CMDB accuracy, they do worry about what CMDB inaccuracy *causes*. 

### The Bottom Line

pedk.ai translates technical reconciliation into four hard executive value levers:

| Executive Pain Point | Business Impact | pedk.ai's Answer |
|----------------------|-----------------|------------------|
| **The "Integration Tax" (OPEX)** | Operators spend millions annually on L2/L3 engineers blindly hunting for root causes because their maps are wrong. This is dead OPEX. | By eliminating the Dark Graph, troubleshooting goes from "hunting in the dark" to "following a lit path", dropping MTTR and structural OPEX. |
| **Silent Revenue Leakage** | Sleeping cells report as "healthy" but serve zero traffic. Customers churn; SLAs are breached; revenue leaks silently. | pedk.ai finds the failures that traditional element managers and alarms miss entirely, safeguarding top-line revenue. |
| **Phantom CapEx / Licences** | Decommissioned but fully-licenced instances (Phantom Nodes) cost real money in software renewals and vendor maintenance. | pedk.ai identifies assets generating zero telemetry for months, enabling immediate licence clawbacks and hard savings. |
| **Headline / Brand Risk** | Major outages happen because an undocumented dependency cascaded unexpectedly. Brand damage is severe. | Continuous reconciliation makes network brittleness visible *before* the critical collapse occurs. |


## What pedk.ai Does

pedk.ai is an intelligence fabric that sits between your existing systems — element managers, ITSM platforms, CMDBs — and tells you the truth about your network. It cross-correlates what your network *actually does* (telemetry) against what your organisation *thinks* it does (CMDB) and what your engineers *actually know* (ticket resolution patterns).

pedk.ai **augments** your existing tools. It does not replace your element managers, your ITSM platform, or your CMDB. They do what they're designed to do. pedk.ai adds the reconciliation layer they've never had.

pedk.ai already integrates with **ServiceNow** — polling incidents, correlating operator actions with AI recommendations, and computing behavioural feedback to improve over time. Your existing ServiceNow investment becomes more valuable, not redundant.


## How It Works — Day 1

pedk.ai requires no production access on Day 1. No write access to any system. No sensitive data.

You provide three read-only historical datasets:

| What You Share | What It Contains | What pedk.ai Finds |
|----------------|------------------|-------------------|
| **CMDB Snapshot** | Your Configuration Items and their declared relationships | The "documented truth" — what you think the network looks like |
| **Telemetry History** | 12 months of PM counters, event logs, alarm records | The "physical truth" — what the network actually did |
| **Ticket Archive** | Incident and change ticket history | The "human truth" — how your engineers actually fix problems |

Within 48 hours, pedk.ai delivers a **Divergence Report**:

- Entities generating telemetry with no CMDB record (**undocumented infrastructure**)
- CMDB records with zero telemetry for months (**phantom assets** consuming licence fees)
- Hardware swaps detected from telemetry/CMDB mismatches (**identity mutations**)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns

**Zero risk. Zero disruption. Proven value before any deeper conversation.**


## Core Capabilities

### Dark Graph Reconciliation

pedk.ai's foundational capability. Discovers the six types of divergence between network reality and documented intent:

- **Undocumented entities** — infrastructure that exists but isn't in the CMDB
- **Phantom assets** — CMDB entries for infrastructure that no longer exists or functions
- **Undocumented connections** — real dependencies between systems that no document records
- **Phantom connections** — documented links that carry no traffic
- **Attribute drift** — parameters that have been changed in the field but never updated
- **Identity mutations** — hardware swaps where the function persists but the physical entity has changed

### Abeyance Memory

pedk.ai's unique differentiator. Traditional monitoring processes events in real-time and discards what it can't resolve. pedk.ai does not discard. It remembers.

Unresolved technical fragments — a CLI output pasted into a ticket note, a transient telemetry anomaly, a reference to an unknown IP address — are held in persistent semantic storage using telecom-specific 1536-dimensional embeddings. Days, weeks, or months later, when a new piece of evidence arrives that matches, pedk.ai **connects the dots** across time and across data types.

The system is implemented with a **5-dimension correlation engine** (semantic similarity, topological proximity, temporal alignment, operational fingerprint, entity overlap) that can connect different descriptions of the same problem across network domains — something no text-matching system can achieve. Fragments follow a managed lifecycle with source-specific retention (alarms 90 days, change records up to 2 years), relevance decay, and cold storage archival.

No competing product does this. Nokia's NMA agents discard context after task completion. ServiceNow's RAMC correlation requires the same CI/metric recurring in the same timeframe. Google's MINDR processes events and moves on. Abeyance Memory is patient. It finds connections that no human analyst could spot across thousands of tickets and millions of events.

### Sleeping Cell Detection

Sleeping cells are silent failures — a cell reports "healthy" to the element manager but serves zero users. No alarms fire. The gap itself is the signal.

pedk.ai detects sleeping cells through multiple complementary methods:

- **Baseline comparison** — flagging cells with zero traffic when historical patterns predict activity
- **Neighbour analysis** — identifying cells performing significantly worse than their geographic neighbours
- **Correlation monitoring** — detecting when KPI relationships that should move together suddenly decouple
- **Multi-dimensional pattern recognition** — identifying complex degradation patterns that no single threshold would catch
- **UE measurement analysis** — comparing device-reported signal quality against cell-reported status
- **Handover pattern analysis** — detecting asymmetric handover behaviour indicating silent failures

### Customer Experience Intelligence

Every telco predicts churn. pedk.ai does something different: it connects **network root causes** to **individual customer impact**.

By correlating cell-level performance with subscriber connection patterns, pedk.ai constructs a per-subscriber Quality of Experience score spanning coverage, data throughput, voice quality, service availability, and connection stability. When scores decline for a cluster of subscribers, pedk.ai identifies both the affected customers and the network fault causing the degradation — enabling proactive care before customers complain.

### Autonomous Network Operations

pedk.ai provides NOC teams with AI-generated situational reports (SITREPs) that explain anomalies in plain language, identify root causes through graph-based analysis, and recommend actions. Support for multi-service anomaly detection across mobile, voice, SMS, and landline services, with congestion management and emergency compliance monitoring.

### AI-Driven Capacity Planning

Data-driven network densification recommendations based on real KPI hotspots, with CapEx optimisation within budget constraints.


## Operator Control — Always

pedk.ai's autonomy is a spectrum. You choose your comfort level:

| Level | What pedk.ai Does | What You Do |
|:-----:|------------------|-------------|
| **Advisory** | Generates reports and recommendations. Takes zero action. | Full manual control. |
| **Assisted** | Creates draft tickets with pre-populated fields. | You review and dispatch every ticket. |
| **Supervised** | Executes routine actions with an override window. | You can veto any action before it takes effect. |
| **Gated** | Executes approved action types with safety gates. | You review the audit trail. Kill-switch available. |

**Default: Advisory.** You advance only when you're ready.

pedk.ai learns from what your operators actually do — not just button clicks, but real operational actions. When pedk.ai recommends an action and your operator takes a different one, that delta is the learning signal that makes pedk.ai smarter over time.


## Trust Progression

| Timeline | What Happens | Your Risk |
|----------|-------------|-----------|
| **Day 1** | Offline analysis of historical data. Divergence Report delivered. | None. Read-only. No production access. |
| **Month 3** | Shadow mode alongside existing tools. Accuracy validated. | None. Read-only production feeds. |
| **Month 6** | Advisory mode. SITREPs generated for NOC team. | None. Advisory only. No automated actions. |
| **Month 12+** | Deeper integration discussed only after proven value. | Earned trust. You decide the pace. |


## Standards & Compliance

- **TM Forum**: TMF642 Alarm Management API, TMF628 Performance Management API
- **Multi-vendor**: Ericsson (XML), Nokia (JSON), SNMP — normalised into unified internal format
- **Telemetry**: 6-domain ingestion — RAN, Transport, Core, Fixed Broadband, Enterprise, Power — via Apache Kafka
- **Embeddings**: Telecom-specific T-VEC model (1536-dim) for domain-accurate semantic search — outperforms generic models by 30%+ on telecom tasks
- **Security**: JWT authentication, hierarchical RBAC, tenant data isolation, GDPR consent enforcement, data sovereignty controls
- **Multi-tenancy**: Full tenant isolation — every data table scoped by tenant, no cross-tenant access
- **LLM**: Vendor-neutral — supports cloud-hosted and on-premises models for data sovereignty requirements
- **Real-time**: Server-Sent Events (SSE) alarm streaming for live NOC dashboards
- **ServiceNow**: Production integration — polls incidents, ingests operator actions, computes behavioural feedback


## Cost Advantage

pedk.ai's architecture delivers enterprise-grade telecom intelligence at a fraction of incumbent pricing:

| Capability | Incumbent Cost | pedk.ai |
|------------|---------------|---------|
| **AI inference** | Cloud LLM APIs: $0.01–$0.06 per 1K tokens, scaling with volume | Local T-VEC (CPU, 3GB) + local LLM: **zero marginal cost per call** |
| **Licensing** | ServiceNow ITSM + ITOM: $250–$360/agent/month. 100 agents = $300K–$430K/year | No per-agent model. Annual subscription based on network size |
| **Deployment** | 6–18 month implementation. Consulting fees 1–3x annual licence | Docker single-command deployment. Operational in days, not months |
| **Data sovereignty** | Cloud-only (ServiceNow SaaS, Google Vertex AI). Data leaves your premises | Runs entirely on-premises. Your data never leaves your network |

For operators who cannot justify ServiceNow's total cost of ownership (3–5x the licence fee), pedk.ai delivers comparable operational intelligence at 10–20% of the cost.


## Deployment

pedk.ai deploys on Kubernetes with Docker containers. Cloud-hosted SaaS or on-premises. Supports PostgreSQL with TimescaleDB for time-series analytics, Apache Kafka for telemetry streaming, and vector search for semantic intelligence.

Validated on Oracle Cloud (ARM-based infrastructure) and Docker Compose for single-command deployment. Kubernetes manifests available for production scaling.

No heavyweight infrastructure requirements. No rip-and-replace migration. pedk.ai operates alongside your existing stack from Day 1.


## Quality Process

pedk.ai has been subjected to a rigorous multi-phase review cycle:

- **Three-pass technical audit**: forensic code review, architecture viability assessment, and adversarial red-team review
- **Five-member executive committee**: spanning operations, strategy, engineering, QA, and executive leadership
- **Formal remediation cycle**: structured gap analysis with tracked resolution
- **Erdos AI methodology**: independent assessment using the Erdos Enterprise AI Deployment Framework, covering product readiness, business case integration, and workforce readiness

This is not a prototype presented as a product. It is an engineered system that has been systematically challenged, found wanting in specific areas, and improved through structured remediation.


## Evidence-Based Approach

pedk.ai uses pluggable mathematical frameworks for evidence fusion — selecting the optimal approach based on your data landscape. Customers with rich telemetry streams benefit from one methodology; those with sparse, policy-gated environments benefit from another.

Causal inference uses established statistical methods for time-series analysis, with a roadmap to incorporate more advanced techniques for non-linear and multi-variable causality as they mature.

The approach is configurable per deployment. No one-size-fits-all.


## How pedk.ai Compares

| Capability | ServiceNow | Nokia | Ericsson | pedk.ai |
|------------|-----------|-------|----------|---------|
| **Cross-domain correlation** | Same CI/metric must recur in same timeframe | Ontology engine normalises domains | Multi-agent end-to-end | 5-dimension semantic fusion across different vocabulary and domains |
| **Unresolved evidence** | Discards after processing | Discards after task completion | Processes in real-time | **Holds indefinitely** in Abeyance Memory |
| **CMDB enrichment** | Active discovery (ping-based, blind behind firewalls) | Vendor-specific topology | Digital twin from telemetry | Passive discovery from telemetry + tickets + CMDB cross-correlation |
| **Model serving** | Cloud SaaS only | Cloud-implied | Cloud (Vertex AI, AWS) | **Local-only option**: zero cloud dependency |
| **Cost** | $300K–$8M/year (licence + implementation) | Bundled with network equipment | Managed services model | Enterprise license based on network size |
| **Deployment time** | 6–18 months | Requires Nokia-dominant environment | Requires EIAP ecosystem | Days to weeks (Docker) |

pedk.ai does not compete with these platforms. It **augments** them — adding the intelligence layer that makes existing investments work harder.


## The Conversation pedk.ai Enables

pedk.ai doesn't ask you to trust it. It asks you to **test it**.

Share historical data. Get a Divergence Report. If it finds value, continue the conversation. If it doesn't, you've lost nothing.

The question isn't whether your CMDB has gaps. It does. Every CMDB does. The question is whether you want to know what they are.
