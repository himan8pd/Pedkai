# Pedk.ai — Product Specification Document

**Version:** 2.0  
**Date:** 2026-03-05  
**Status:** Authoritative — Single Source of Truth  
**Classification:** Product Confidential  
**Methodology:** [Erdos AI Enterprise AI Deployment Methodology](/Users/himanshu/Projects/Erdos%20Research)  
**Supersedes:** All root-level vision, roadmap, review, and strategy documents (see [§16 Document Catalogue](#16-document-catalogue))

> [!NOTE]
> This document was produced following the **Erdos AI Enterprise AI Deployment Methodology** — a structured, persona-driven approach that routes analysis through three lenses (Product, Business Case, Skills) to produce a comprehensive product specification. Superseded documents are archived in `docs/archive/`.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Product Vision & Value Proposition](#2-product-vision--value-proposition)
3. [Architecture Overview](#3-architecture-overview)
4. [Abeyance Memory — Pedk.ai's Core Differentiator](#4-abeyance-memory--pedkais-core-differentiator)
5. [Evidence Fusion Methodology](#5-evidence-fusion-methodology)
6. [Feature Inventory](#6-feature-inventory)
7. [Operator Feedback & Human-in-the-Loop](#7-operator-feedback--human-in-the-loop)
8. [Causal Inference Methodology](#8-causal-inference-methodology)
9. [Data Model & Multi-Tenant Design](#9-data-model--multi-tenant-design)
10. [Synthetic Data & Testing Infrastructure](#10-synthetic-data--testing-infrastructure)
11. [TMF Standards Compliance](#11-tmf-standards-compliance)
12. [Deployment Model](#12-deployment-model)
13. [Security Model](#13-security-model)
14. [Erdos Lens Analysis](#14-erdos-lens-analysis)
15. [Technology Stack](#15-technology-stack)
16. [Implementation Phases & Maturity Assessment](#16-implementation-phases--maturity-assessment)
17. [Governance & Quality Standards](#17-governance--quality-standards)
18. [Document Catalogue](#18-document-catalogue)

---

## 1. Problem Statement

> **Erdos Template:** We need to [AI capability] in order to [business outcome] for [affected users], within the constraints of [limits], measured by [metric], owned by [accountable role].

**We need to** continuously reconcile the physical, electronic reality of large enterprise network infrastructure against its documented, bureaucratic intent (CMDBs, change tickets, architecture diagrams) **in order to** eliminate the "Dark Graph" — the mathematically provable divergence between what the network actually *is* and what the organisation *thinks* it is — **for** NOC engineers, IT operations leaders, and service assurance teams at Tier-1 telecom operators (Vodafone/Jio/Verizon scale), **within the constraints of** multi-vendor environments (Ericsson, Nokia, Huawei), TM Forum Open APIs (TMF628, TMF642), GDPR/ICO data protection requirements, OFCOM regulatory obligations, and zero-disruption deployment mandates, **measured by** CMDB accuracy improvement, mean time to resolve (MTTR) reduction, undocumented dependency discovery rate, and operational efficiency improvement, **owned by** the VP of IT Operations / Head of Service Management.

### Why This Problem Exists

Every global enterprise is fundamentally blind to its own nervous system. The physical reality of infrastructure (telemetry, logs, packet flows) is structurally out of sync with the bureaucratic intent (static CMDBs, forgotten change tickets, outdated architecture diagrams). This divergence has four root causes:

| Cause | Description | Data Availability |
|-------|-------------|-------------------|
| **Intrusion & Anomaly** | Malicious actors traverse infrastructure in ways no CMDB records | HIGH (CasinoLimit dataset) |
| **Tribal Knowledge** | Engineers maintain the real state in their heads; CMDBs capture the minimum | LOW (requires ticket corpus) |
| **Secure Infrastructure** | CyberArk-protected, air-gapped assets invisible to telemetry | NONE (synthetic simulation) |
| **Multi-Party Handover** | Decades of site deployments across dozens of contractors, each with independent identifiers | NONE (synthetic simulation) |

### Why Now

- Post-5G SA deployment: 200–400 OSS/BSS tools, >1,200 integration points per Tier-1 operator
- OPEX growing 8–12% YoY; 35–50% consumed by maintenance and integration tax
- Incumbent AI Service Mapping (BMC/ServiceNow) relies on active discovery pinging — blind behind firewalls
- Pedk.ai finds what active scanning cannot: the dependencies that exist between firewalled, air-gapped, or policy-shielded infrastructure

### The Bottom Line

Nobody in the C-suite wakes up worrying about CMDB accuracy. But they do worry about what CMDB inaccuracy *causes*. Pedk.ai translates technical reconciliation into four hard executive value levers:

| Executive Pain Point | Business Impact | Pedk.ai's Answer |
|----------------------|-----------------|------------------|
| **The "Integration Tax" (OPEX)** | Tier-1 operators spend millions annually on L2/L3 engineers blindly hunting for root causes because their maps are wrong. This is dead OPEX. | By eliminating the Dark Graph, troubleshooting goes from "hunting in the dark" to "following a lit path", structurally lowering MTTR and OPEX. |
| **Silent Revenue Leakage** | Sleeping cells report as "healthy" but serve zero traffic. Customers churn; SLAs are breached; revenue leaks silently. | Pedk.ai finds the failures that traditional element managers and alarms miss entirely, safeguarding top-line revenue. |
| **Headline / Regulatory Risk** | Major outages (like 999/911 failures) happen because an undocumented dependency cascaded unexpectedly. Fines are massive; brand damage is worse. | Continuous, automatic reconciliation makes network brittleness visible *before* the critical collapse occurs. |
| **Phantom CapEx / Licences** | Decommissioned but fully-licenced instances (Phantom Nodes) cost real money in software renewals and vendor maintenance. | Pedk.ai identifies assets generating zero telemetry for months, enabling immediate licence clawbacks and hard savings. |

---

## 2. Product Vision & Value Proposition

### Vision

Pedk.ai is an **AI-Native Operational Reconciliation Engine** — the intelligence fabric that connects existing enterprise systems (ITSM, BSS/OSS, vendor NMS) to translate raw electronic chaos into documented reality.

> [!IMPORTANT]
> **Pedk.ai does not replace Ericsson, Nokia, ServiceNow, or Amdocs.** Element managers exist for critical reasons: real-time control, vendor-specific configuration, regulatory compliance, and operational safety. Pedk.ai sits *above* these systems as a reconciliation layer. It observes, correlates, and keeps the business aware of the continuous churn between what element managers report and what the CMDB records. Pedk.ai augments — it never displaces.

### The Dark Graph

The Dark Graph is any element of the real network topology that diverges from what the CMDB declares. It is Pedk.ai's moat and core value. It manifests at every level:

| Divergence Type | Description | Example |
|-----------------|-------------|---------|
| **Dark Nodes** | Entities that physically exist but have no CMDB record | Elastically scaled VNF emitting telemetry; CMDB unaware |
| **Phantom Nodes** | CMDB records for entities that no longer exist | Decommissioned cell site still listed as "active" |
| **Dark Edges** | Undocumented connections between entities | SSH tunnel between two servers behind a firewall |
| **Phantom Edges** | CMDB-declared connections that carry no traffic | Firewall rule decommissioned but never removed from CMDB |
| **Dark Attributes** | Properties recorded incorrectly or not at all | Radio link parameters adjusted in the field, never updated |
| **Identity Mutations** | Same logical function served by different physical entity | Emergency hardware swap: new serial number, same IP |

### Value Proposition

| Value Lever | Mechanism | Impact |
|-------------|-----------|--------|
| **CMDB Reconciliation** | Offline ingestion of historical ticket data → automated discovery of undocumented dependencies | 300+ missing dependencies discovered in 48 hours |
| **MTTR Reduction** | Cross-domain causal root cause analysis via inferred topology | 25–45% improvement in mean time to resolve |
| **Operational Awareness** | Continuous reconciliation of live element manager output against CMDB records | Real-time visibility into infrastructure churn that accumulates silently |
| **Proactive CX** | Churn-to-anomaly correlation triggers automated care workflows | At-risk customers identified before they complain |

### Go-to-Market: The "Read-Only Wedge"

Pedk.ai's Day 1 entry point requires **zero write access** and **zero sensitive data exposure**. The customer provides three read-only datasets:

| Data Source | Format | Purpose |
|-------------|--------|---------|
| **CMDB snapshot** | CSV/JSON export of Configuration Items and relationships | The "declared truth" — what the organisation thinks the network looks like |
| **Telemetry time-series** | Historical PM counters, event logs, alarm history (12 months minimum) | The "physical truth" — what the network actually did |
| **ITSM ticket archive** | CSV export of incident and change tickets | The "human truth" — how engineers actually troubleshot and fixed problems |

#### The Three-Way Cross-Correlation

Pedk.ai's value comes from cross-correlating these three data sources against each other:

1. **Telemetry vs CMDB → Dark Nodes & Phantom CIs**: When telemetry arrives from entities that have no CMDB record, Pedk.ai identifies Dark Nodes. When CMDB CIs generate zero telemetry for months, Pedk.ai flags them as Phantom CI candidates — still consuming licence fees, wasting operational attention, but providing no service.
2. **Telemetry vs CMDB → Identity Mutations**: When telemetry shows a CI with a different serial number, MAC address, or hardware model than the CMDB records, Pedk.ai detects an undocumented hardware swap — the logical function persists but the physical entity has changed.
3. **Ticket patterns vs CMDB → Behavioural Dark Edges**: When engineers consistently access CIs A and B together during troubleshooting (evidence from ticket resolution notes and CI access logs), but the CMDB records no relationship between them, Pedk.ai infers an undocumented operational dependency. These fragments also feed the Abeyance Memory (§4) for future cross-modal matching.
4. **Telemetry patterns → Evidence Fusion**: The evidence fusion engine (§5) populates the vector store with relationship hypotheses. Algorithms score the confidence of each discovered divergence. Over time, corroborated hypotheses graduate through the lifecycle (`CANDIDATE → CORROBORATED → ACCEPTED`).

**Delivery**: Within 48 hours, Pedk.ai hands back a Divergence Report. This is a 3-month sales cycle. The customer risks nothing — they share only historical operational data, not revenue, not customer PII, not billing records. Trust is earned through demonstrated value before any deeper integration is discussed.

---

## 3. Architecture Overview

Pedk.ai is a 5-layer intelligence architecture:

```
┌──────────────────────────────────────────────────────────────────────┐
│                       PEDKAI CONTROL PLANE                           │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 5: Automation & Actuation                                     │
│  • Zero-touch ITSM ticket creation & routing                         │
│  • Granular config changes via Vendor APIs (Ansible/NetConf)         │
│  • Gated autonomous actions with 7 safety gates                      │
│  • Rule: No autonomous action without explainability                 │
│  • OPERATOR ALWAYS IN CONTROL (see §7)                               │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 4: Decision & Policy Engine ("The Constitution")              │
│  • YAML-based declarative business rules                             │
│  • Risk-aware decision making bound by SLA constraints               │
│  • Decision Trace capture, pattern matching, outcome learning        │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 3: Intelligence Engines                                       │
│  • Anomaly Detection (Z-score, statistical)                          │
│  • Root Cause Analysis (graph-based causal inference — see §8)       │
│  • LLM Reasoning (vendor-neutral — see §15)                          │
│  • Decision Similarity Search (vector embeddings)                    │
│  • Evidence Fusion (pluggable methodology — see §5)                  │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 2: Living Context Graph (Decision Memory)                     │
│  • Decision Traces (why decisions were made, not just what)          │
│  • Evidence Snapshots & Constraint History                           │
│  • ABEYANCE MEMORY — Pedk.ai's core differentiator (see §4)          │
│  • Topological Ghost Masks (suppress alarms during maintenance)      │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 1: Omniscient Data Fabric                                     │
│  • Physical Reality: Streaming telemetry (Kafka), PM counters, logs  │
│  • Bureaucratic Intent: ITSM tickets, CMDB exports, change records   │
│  • Multi-vendor ingestion: Ericsson (XML), Nokia (JSON)              │
│  NOTE: Pedk.ai OBSERVES element manager output.                      │
│  It does not replace or bypass element managers.                     │
└──────────────────────────────────────────────────────────────────────┘
```

### Reconciliation Engine

The core mathematical engine uses a **single hypothesis lifecycle** that handles two orthogonal axes:

- **What axis** (topology element): Dark nodes, phantom nodes, identity mutations, dark edges, phantom edges, dark attributes — all pass through `CANDIDATE → CORROBORATED → ACCEPTED → INTEGRATED`
- **Why axis** (causal type): Intrusion, tribal knowledge, secure infrastructure, multi-party handover — all contribute evidence weighted by source type

The evidence fusion methodology (currently Noisy-OR) is **pluggable** — see §5 for alternatives and per-customer selection rationale.

---

## 4. Abeyance Memory — Pedk.ai's Core Differentiator

### What It Is

Abeyance Memory is Pedk.ai's proprietary capability to hold **disconnected, unresolved technical facts** in a latent semantic buffer — indefinitely — until the missing contextual link appears. Unlike conventional monitoring systems that process events in real-time and discard unresolvable data, Pedk.ai *remembers* fragments that don't yet make sense.

### How It Works

1. **Capture**: During routine ticket processing, a NOC engineer pastes a CLI output into a resolution note. The output references an IP address and a timeout error. Pedk.ai ingests this fragment even though no current alarm or CMDB record matches it.

2. **Hold in Abeyance**: The fragment is embedded into the vector store with its full semantic context (timestamp, engineer ID, ticket ID, affected CI, raw text). It sits in the Abeyance Memory — not discarded, not acted upon — waiting.

3. **Snap**: Three weeks later, a new alarm fires from a previously-unknown entity on the same subnet. The anomaly detector flags it. Pedk.ai's similarity search against the Abeyance Memory hits the stored fragment at 0.92 similarity. The two pieces of evidence — a human observation from 3 weeks ago and a machine observation from today — are **snapped together** into a corroborated hypothesis.

4. **Resolve**: The hypothesis graduates from `CANDIDATE` to `CORROBORATED`. Pedk.ai now has a Dark Edge linking two entities that no active scanner could have discovered — because the evidence existed in two different time horizons and two different data modalities (human text + machine telemetry).

### Why It Matters

- **Active discovery scanners** (BMC, ServiceNow) operate in real-time only. If the signal isn't present when the scan runs, it's missed forever.
- **Rule-based correlation engines** require explicit rules to match events. If no rule exists for the specific pattern, it's ignored.
- **Abeyance Memory** is patient. It accumulates evidence across weeks, months, and even years. It doesn't need an explicit rule — it uses semantic similarity to find connections that no human analyst could spot across thousands of tickets and millions of events.

### The Competitive Moat

No competing product holds unresolved evidence in persistent semantic storage with the intent to match it later. This makes Abeyance Memory Pedk.ai's most defensible technical differentiator. It transforms "noise" into "future intelligence."

### Engineering Maturity

| Aspect | Status | Gap |
|--------|--------|-----|
| Vector storage of fragments | ✅ Implemented (pgvector) | — |
| Semantic similarity snapping | ✅ Implemented | Threshold tuning needed per deployment |
| Multi-modal matching (text + telemetry) | ⚠️ Partial | Need structured telemetry-to-text alignment |
| Long-horizon retrieval (>30 days) | ⚠️ Partial | Cold storage retrieval pipeline incomplete |
| Abeyance decay and relevance scoring | ❌ Not implemented | Stale fragments need TTL with relevance weighting |

---

## 5. Evidence Fusion Methodology

### Current Implementation: Noisy-OR

Pedk.ai currently uses the **Noisy-OR** probabilistic model for combining evidence from independent sources. Each evidence source contributes an independent probability of causing a hypothesis to be true, and the combined confidence follows the formula:

```
P(hypothesis | evidence₁, evidence₂, ..., evidenceₙ) = 1 - ∏(1 - pᵢ)
```

This works well when evidence sources are genuinely independent and their influences are additive.

### Critical Assessment

Noisy-OR is a sound starting point, but **no single fusion methodology fits all customers or all evidence types**. Different operators have different evidence profiles, and the mathematical model should be selected to match the customer's data landscape.

### Alternative Methodologies Under Consideration

| Methodology | How It Works | Best For | Limitations | Pedk.ai Fit |
|-------------|-------------|----------|-------------|------------|
| **Noisy-OR** (current) | Each cause independently contributes to hypothesis truth; probabilities combine multiplicatively | Multiple independent telemetry signals confirming an edge or node | Assumes independence; struggles with correlated evidence; no concept of "ignorance" | ✅ Good for Type 1 (intrusion/anomaly) with rich, independent telemetry |
| **Dempster-Shafer Theory** | Assigns belief to *sets* of hypotheses, explicitly representing ignorance; combines via Dempster's Rule | Sparse evidence environments where "I don't know" is a valid and important state | Can produce counter-intuitive results when evidence is highly conflicting; computationally intensive | ✅ Strong fit for Type 3 (secure infrastructure) and Type 4 (multi-party handover) where evidence is sparse and partial |
| **Fuzzy Logic** | Assigns degrees of membership (0–1) to linguistic categories; combines via t-norms | Operator-derived qualitative assessments ("high confidence", "probable cause") | No statistical foundation; subjective membership functions; poor for learning from data | ⚠️ Useful for policy engine rules but not for evidence fusion |
| **Noisy-MAX** | Generalises Noisy-OR to multivalued ordinal variables; effect determined by strongest cause | Severity classification where multiple anomalies compete to determine the dominant failure mode | Requires ordinal ordering of states; less flexible than Noisy-OR for binary hypotheses | ⚠️ Potential fit for alarm severity arbitration |
| **Bayesian Network (full)** | Complete directed acyclic graph with learned conditional probability tables | Rich causal structure with known dependencies between evidence types | Exponential CPT growth; requires training data for structure learning; computationally expensive | 🔮 Future: when sufficient production data is available for structure learning |

### Recommended Strategy: Per-Customer Selection

The evidence fusion methodology should be **configurable per deployment**, matched to the customer's evidence profile:

| Customer Profile | Primary Evidence | Recommended Methodology |
|-----------------|-----------------|------------------------|
| Operator with rich telemetry (Kafka streams, gNMI) | Dense, real-time, independent signals | **Noisy-OR** (current) |
| Operator with sparse, policy-gated data | Partial ticket references, fragmentary evidence | **Dempster-Shafer** |
| Operator with qualitative NOC assessments | Operator judgment, experience-based ratings | **Fuzzy Logic overlay** on Noisy-OR |
| Operator with extensive historical ticket corpus | Behavioural patterns across years of ITSM data | **Full Bayesian Network** (with structure learning) |

> [!IMPORTANT]
> **Product roadmap item**: Implement a `FusionMethodologyFactory` that selects the appropriate evidence fusion engine at deployment configuration time. V1 ships with Noisy-OR. V2 adds Dempster-Shafer for sparse-evidence deployments. See [§17 Task Backlog](#17-governance--quality-standards) for engineering tasks.

---

## 6. Feature Inventory

> [!WARNING]
> **Engineering Maturity Notice**: The features listed below represent the product's designed scope. Many are implemented at proof-of-concept or early-prototype maturity. Significant engineering work is required to bring them to production-ready quality. Each feature includes a maturity status. Items marked ⚠️ or 🔨 require focused engineering before they can be demonstrated to customers with confidence.

### Feature 1: Dark Graph Reconciliation (The Wedge)

**Why this is Feature #1**: This is Pedk.ai's most immediately deliverable capability. It can be demonstrated using **read-only historical data** with **zero infrastructure changes** on the customer side. It is the proof point that earns trust.

| Capability | Description | Maturity |
|------------|-------------|:--------:|
| **Divergence Report** | Machine-generated report of all dark nodes, phantom nodes, identity mutations, dark/phantom edges discovered from historical data | 🔨 In Progress |
| **Datagerry CMDB sync adapter** | Periodic snapshots of CMDB state into Pedk.ai's internal representation | 🔨 In Progress |
| **CasinoLimit telemetry parser** | Three telemetry streams: network flows, syscalls, MITRE labels | 🔨 In Progress |
| **Topological Ghost Masks** | Suppresses alarms during planned maintenance by cross-referencing change schedules | 🔨 In Progress |
| **Behavioural Dark Graph** | Infers operational dependencies from how engineers actually troubleshoot (CI access sequences) | 📋 Planned |
| **Multi-party identity resolution** | Cross-lifecycle identifier clustering from unstructured deployment documents | 📋 Planned |

**Day 1 delivery model**: Customer provides read-only access to three historical datasets: CMDB snapshot, telemetry time-series (12 months), and ITSM ticket archive (see [Go-to-Market: The Read-Only Wedge](#go-to-market-the-read-only-wedge) for the three-way cross-correlation mechanism). Within 48 hours, Pedk.ai delivers a Divergence Report identifying Dark Nodes, Phantom CIs, Identity Mutations, and Behavioural Dark Edges. Value demonstrated before any production integration.

### Feature 2: Autonomous Network Operations (ANOps)

| Capability | Description | Maturity |
|------------|-------------|:--------:|
| Multi-service anomaly detection | Z-score statistical analysis across mobile, voice (VoLTE), SMS, landline | ✅ Implemented |
| Graph-based root cause analysis | Recursive graph traversal mapping anomalies to upstream dependencies | ✅ Implemented |
| LLM-powered SITREPs | Vendor-neutral LLM generates actionable explanations for NOC engineers | ✅ Implemented |
| Sleeping cell detection | Multi-method silent failure detection (see below) | ⚠️ Code exists but not wired into scheduler |
| Congestion management | PRB utilisation vs latency correlation, DSS activation recommendations | ✅ Implemented |
| Emergency compliance | 999/911 dial-out blockage detection and life-critical traffic override | ✅ Implemented |

#### Sleeping Cell Detection — Technical Methodology

Sleeping cells are the hardest network failures to detect because **they generate no alarms**. The cell reports "green" to the element manager — but it serves zero users. The alarm gap itself is the diagnostic signal. Pedk.ai uses six complementary detection methods:

| # | Method | How It Works | What It Catches |
|---|--------|-------------|----------------|
| 1 | **Zero-User Baseline Comparison** | Compares active user count against historical baseline for same cell, same time-of-day, same day-of-week. If users drop to zero when the baseline predicts >50, the cell is flagged. | Complete silent failures — cell is up but not serving any traffic |
| 2 | **Neighbour-Reference Z-Score** | For each cell, calculates Z-score of key KPIs (throughput, RRC connections, PRB utilisation) relative to its geographic and topological neighbours. Healthy neighbours with similar coverage should show similar traffic patterns. | Partial degradation — cell serves some traffic but significantly less than neighbours, indicating it's silently shedding load |
| 3 | **KPI Correlation Breakpoint Detection** | Monitors the correlation between KPI pairs that should move together (e.g., number of users ↔ downlink throughput ↔ PRB utilisation). When correlations that have been stable for weeks suddenly break (users rise but throughput doesn't), regression analysis flags the anomaly. | Subtle degradation — cell appears operational but internal performance chains are broken |
| 4 | **Deep Autoencoder Reconstruction Error** | Trains an autoencoder on "normal" multi-KPI vectors per cell type. At detection time, measures reconstruction error. High reconstruction error indicates KPI patterns that don't conform to learned normal behaviour, even when no individual KPI breaches a threshold. | Complex multi-dimensional failures that no single-KPI threshold would catch |
| 5 | **MDT-Based Triangulation** (where available) | Uses Minimisation of Drive Tests (MDT) reports from UE devices. If devices in a cell's coverage area consistently report poor RSRP/SINR while the cell itself reports normal operation, the cell is failing to provide service despite being "up." | Radio coverage failures where the cell is operational but its signal is impaired |
| 6 | **Traffic Handover Asymmetry** | Analyses handover patterns. If neighbouring cells consistently hand *in* to the suspect cell but it never hands *out*, or if its handover success rate drops while neighbours remain stable, the cell may be accepting connections but failing to maintain them. | Cells that accept incoming handovers but silently drop users after connection |

**Design principle**: Sleeping cells produce **no alarms** — the alarm gap is the ground-truth signal. The synthetic data from Sleeping-Cell-KPI-Data is specifically designed to generate sleeping cell scenarios with zero alarms, forcing Pedk.ai to detect them through KPI pattern analysis.

### Feature 3: AI-Driven Capacity Planning

| Capability | Description | Maturity |
|------------|-------------|:--------:|
| Data-driven densification engine | Queries real KPI hotspots (congestion >85%) from time-series store | ⚠️ Prototype |
| CapEx optimisation | Greedy ROI-based site placement selection within budget constraints | ⚠️ Prototype |
| Regional densification dashboard | Integrated visualisation in NOC UI | ⚠️ Prototype |

### Feature 4: Customer Experience Intelligence

| Capability | Description | Maturity |
|------------|-------------|:--------:|
| Per-subscriber network QoE scoring | Multi-dimensional quality score per customer based on cells they connect to | ⚠️ Prototype |
| Churn-to-anomaly correlation | Maps network degradation events to at-risk subscribers | ⚠️ Prototype |
| Proactive care automation | Automated care triggers and notification logging | ⚠️ Prototype |

#### Customer Experience Intelligence — Technical Methodology

The core technical challenge is connecting **network-layer events** (which Pedk.ai sees) to **individual customer impact** (which matters to the business). The pipeline works as follows:

**Step 1: Per-Subscriber Network QoE Scoring**

Each subscriber connects to specific cells at specific times. By joining subscriber connection records (from BSS data, when available in future phases; or from anonymised network attachment records for Day 1) with cell-level KPIs, Pedk.ai constructs a **per-subscriber Quality of Experience (QoE) score**:

| QoE Dimension | KPI Source | Weight |
|---------------|-----------|:------:|
| Coverage reliability | RSRP/SINR from serving cell(s) | 30% |
| Data experience | DL/UL throughput, latency | 25% |
| Voice quality | VoLTE MOS, call setup success rate | 20% |
| Service availability | Sleeping cell exposure, outage duration in coverage area | 15% |
| Stability | Handover failure rate, RRC re-establishments | 10% |

The score is calculated on a rolling 7-day window. A subscriber whose primary cells are degrading will see their QoE score decline even before they notice or complain.

**Step 2: Churn Risk Correlation**

When QoE scores decline for a cluster of subscribers in a geographic area, Pedk.ai correlates this with:
- Historical churn patterns: subscribers with sustained QoE < threshold for >14 days have statistically higher churn rates
- SLA tier: Enterprise and Gold subscribers have lower tolerance thresholds
- Competitive coverage: areas where competitor coverage is strong amplify churn risk

**Step 3: Proactive Care Triggers**

When the correlation engine identifies at-risk subscribers, Pedk.ai generates:
- **NOC SITREP**: identifying the network root cause (e.g., degraded cell, sleeping cell in coverage area)
- **CX Alert**: identifying affected subscribers by segment, SLA tier, and estimated revenue at risk
- **Care Recommendation**: suggesting proactive actions (e.g., SMS apology, data credit, priority repair scheduling)

**Key insight**: Pedk.ai's value is not the churn prediction model itself (every telco has one). The value is **connecting the network root cause to the customer impact** — something no existing system does because network data and customer data live in different silos. Pedk.ai's Dark Graph reconciliation is what bridges them.

### Strategic Capabilities (Future Roadmap)

| Capability | Description | Maturity |
|------------|-------------|:--------:|
| BSS Data Layer | Revenue and billing context for risk assessment | 🔮 Future roadmap — requires earned customer trust (see §13) |
| Policy Engine ("Constitution") | YAML-based declarative business rules for SLA enforcement | ✅ Implemented |
| Semantic Context Graph | Recursive reasoning across multi-hop relationships | ⚠️ Prototype |
| Closed-Loop RL Evaluator | Reinforcement learning from incident closure outcomes | ⚠️ Prototype |

---

## 7. Operator Feedback & Human-in-the-Loop

> [!IMPORTANT]
> **Pedk.ai can be autonomous, but it does not have to be.** Autonomy is a spectrum. Every customer chooses their comfort level. The operator is always in control.

### The Autonomy Spectrum

| Level | Name | Pedk.ai's Role | Operator's Role |
|:-----:|------|---------------|-----------------|
| 0 | **Advisory Only** | Generates SITREPs. Recommends actions. Takes zero action. | Full manual control. Uses Pedk.ai as a diagnostic assistant. |
| 1 | **Assisted** | Creates draft tickets, pre-populates fields. | Reviews, approves, and dispatches every ticket. |
| 2 | **Supervised** | Executes routine actions (e.g., ticket creation) with operator override window. | Monitors, can veto any action within a configurable window. |
| 3 | **Gated Autonomous** | Executes pre-approved action types (e.g., alarm acknowledgement) with 7 safety gates. | Reviews safety gate audit trail. Can invoke kill-switch at any time. |

**Default deployment: Level 0.** The customer advances only when they choose to.

### How Operator Feedback Works

Pedk.ai captures operator feedback through **three channels**, ranked by signal quality:

| Channel | Signal Type | Quality | Implementation |
|---------|------------|:-------:|----------------|
| **Behavioural Observation** | What the operator *actually does* after receiving a SITREP — which tickets they open, which CIs they check, which resolution actions they take, how they modify Pedk.ai's draft tickets | 🟢 Highest | Ingests operator actions from ITSM (ticket modifications, CI interactions, resolution codes) and correlates with Pedk.ai's recommendations |
| **Structured Assessment** | Operator rates decision quality on a scale (e.g., accuracy 1–5, relevance 1–5, actionability 1–5) with optional freeform notes | 🟡 Medium | Multi-dimensional assessment forms integrated into NOC dashboard |
| **Quick Signal** | Thumbs up / thumbs down on a specific recommendation | 🔴 Lowest | Simple binary feedback; useful for aggregate trends but insufficient for technical nuance |

> [!IMPORTANT]
> **Thumbs up/down alone is a poor quality signal for a technically nuanced product.** A "thumbs down" tells Pedk.ai that something was wrong but not *what* was wrong — was the root cause identification incorrect? Was the recommendation impractical? Was the severity miscalibrated? Pedk.ai prioritises behavioural observation (what did the operator *actually do*?) because actions speak louder than clicks.

### Feedback Loop Mechanics

1. Pedk.ai generates a SITREP and recommended action
2. Operator reads the SITREP and takes action (or ignores it)
3. Pedk.ai observes the operator's actual response (via ITSM integration)
4. The delta between "what Pedk.ai recommended" and "what the operator actually did" is the **learning signal**
5. This delta updates the Decision Memory's relevance weighting and the similarity search's ranking function
6. Over time, Pedk.ai's recommendations converge toward the patterns that operators actually follow

### Engineering Maturity

| Aspect | Status | Gap |
|--------|--------|-----|
| Thumbs up/down binary feedback | ✅ Implemented | — |
| Multi-operator feedback aggregation | ✅ Implemented (junction table) | Need anti-gaming safeguards |
| Behavioural observation pipeline | ❌ Not implemented | Critical gap — highest value signal channel |
| Structured multi-dimensional assessment | ❌ Not implemented | Need NOC dashboard integration |
| ITSM action ingestion (ServiceNow/Remedy) | ❌ Not implemented | Depends on customer ITSM platform |
| Decision recommendation → outcome tracking | ⚠️ Partial | RL evaluator exists but not fully wired |

---

## 8. Causal Inference Methodology

### Current Implementation: Granger Causality

Pedk.ai uses **Granger Causality** for time-series causal inference — testing whether past values of metric X improve the forecast of metric Y beyond Y's own history. Implementation includes ADF stationarity tests, automatic differencing, and dynamic candidate metric discovery.

### Critical Assessment

Granger Causality is appropriate for V1 but has known limitations that will constrain Pedk.ai's effectiveness as it scales to more complex network topologies:

| Limitation | Impact on Pedk.ai |
|------------|-----------------|
| Detects only **linear** relationships | Non-linear cascading failures (e.g., exponential congestion buildup) will be missed |
| Requires **stationarity** | Real network KPIs are often non-stationary (trending traffic growth, seasonal patterns) |
| **Bivariate** by default | Real network failures involve multi-variable cascading; pairwise testing misses confounders |
| **Omitted variable bias** | If the true cause isn't in the candidate set, Granger will attribute causality to a correlated proxy |

### Alternative Methodologies

| Method | How It Works | Strengths | Limitations | Pedk.ai Roadmap |
|--------|-------------|-----------|-------------|:-------------:|
| **Granger Causality** (current) | VAR model: does X's past predict Y's future? | Simple, fast, well-understood | Linear only, bivariate, stationarity required | ✅ V1 |
| **Transfer Entropy** | Information-theoretic: how much does knowing X's past reduce uncertainty in Y's future? | Captures **non-linear** dependencies; model-free | Computationally expensive; sensitive to data volume and discretisation | 🔮 V2 |
| **PCMCI** (Peter Clark – Momentary Conditional Independence) | Constraint-based causal graph discovery with conditional independence tests adapted for time series | Discovers full **causal graph** (not just pairwise); handles multivariate; controls for confounders | Computationally intensive; requires large sample sizes | 🔮 V2 |
| **Convergent Cross Mapping (CCM)** | Dynamic systems theory: if X causes Y, then Y's history contains information about X (attractor reconstruction) | Works for **non-linear, non-separable** systems; identifies weak causality Granger misses | Requires long time series; embedding parameter sensitivity; may show false bidirectional causality under strong forcing | 🔮 V3 |
| **Structural VAR (SVAR)** | VAR with contemporaneous effect identification via restrictions | Models simultaneous causation (events happening at same time step) | Requires domain knowledge for identifying restrictions; still linear | 🔮 V2 |

### Recommended Roadmap

- **V1** (current): Granger Causality with ADF stationarity tests
- **V2**: Add Transfer Entropy for non-linear detection and PCMCI for full causal graph discovery
- **V3**: Add CCM for complex coupled systems (relevant for RAN-Transport-Core cascading failures)
- **Per-customer selection**: Like evidence fusion (§5), causal methodology should be configurable per deployment based on data characteristics

---

## 9. Data Model & Multi-Tenant Design

### Multi-Tenancy Architecture

Pedk.ai follows the **industry-standard SaaS multi-tenancy model**:

- **All database tables carry a `tenant_id` column** — every query is scoped by tenant
- **Tenant data boundary is sacrosanct** — no cross-tenant data access, no cross-tenant analytics, no exceptions
- **Each tenant has isolated configuration**, security policies, and data retention rules
- Managed Service Providers (MSPs) hosting Pedk.ai for multiple operators get per-tenant dashboards, never aggregated views

### Core Data Entities

| ORM Model | Purpose |
|-----------|---------|
| `NetworkEntityORM` | Network topology nodes (cells, routers, VNFs) |
| `EntityRelationshipORM` | Topology edges (from_entity → to_entity) |
| `KPIMetricORM` / `KpiSampleORM` | Time-series PM counters |
| `DecisionTraceORM` | Context Graph decision memory (with `embedding_provider`, `embedding_model`) |
| `DecisionFeedbackORM` | Multi-operator feedback (junction table, per-operator voting) |
| `CustomerORM` / `BillingAccountORM` | BSS data layer (future roadmap) |
| `IncidentORM` | Incident lifecycle management |

### Decision Trace Structure

Each decision captured by Pedk.ai includes context (alarm IDs, KPI snapshots, related tickets), binding constraints (SLA, maintenance windows), options considered with risk assessments, the tradeoff made, actions taken, outcomes measured, and learnings extracted. This is the "Decision Memory" — storing *why* decisions were made, not just *what* happened.

### Storage Architecture

| Tier | Purpose | Technology | Retention |
|------|---------|------------|-----------|
| **Hot** | Anomaly detection, real-time dashboard | Redis / TimescaleDB Hypertable | 24–48 hours |
| **Warm** | RCA, graph traversal, decision memory | PostgreSQL (JSONB + pgvector) | 30–90 days |
| **Cold** | Model training, historic audit, compliance | S3 / Parquet / Apache Iceberg | 1–7 years |

---

## 10. Synthetic Data & Testing Infrastructure

> [!IMPORTANT]
> Pedk.ai's synthetic data is generated by the **[Sleeping-Cell-KPI-Data](https://github.com/himan8pd/Sleeping-Cell-KPI-Data)** project (`/Users/himanshu/Projects/Sleeping-Cell-KPI-Data`) — producing converged telecom operator datasets for Dark Graph training and ML model development.

### Scale Parameters

The generator produces **~12.2 GB across 17 Parquet files**:

| Parameter | Value |
|-----------|-------|
| Sites | 21,100 across 38 Indonesian provinces (3 timezones) |
| Logical cell-layers | ~66,100 (LTE, NR-NSA EN-DC, NR-SA) |
| Network entities | ~811,000 across 6 domains |
| Relationships | ~1.97M with full cross-domain dependency chains |
| Hourly KPI rows | 47.6M (30 days × 720 intervals × 66k cells) |
| Customers | 1M sampled subscribers with SLA tier data |
| Vendors | Ericsson (55%) and Nokia (45%) naming layers |

### Synthetic Data Quality — The Achilles Heel

> [!CAUTION]
> **The realism of synthetic data is the single most critical risk to Pedk.ai's credibility.** A good engine trained on poorly constructed synthetic data will learn bad behaviours and draw inaccurate conclusions. When such a product encounters real-world data, it will act incorrectly. This must be prevented at all costs.

**Current concerns:**

| Issue | Description | Impact | Required Action |
|-------|-------------|--------|-----------------|
| **UUID V4 overuse** | Synthetic data uses UUID V4 for entity identifiers | Real operators use human-friendly IDs (e.g., `LTE-8842-A`, `SITE-NW-1847`, `WO-2024-NW-1847`) | Implement operator-realistic naming conventions with collision-safe generation |
| **Scenario realism** | Injected faults may not reflect real-world failure patterns | Model learns synthetic failure modes that don't occur in production | Validate scenario definitions against published post-incident reports from Tier-1 operators |
| **Temporal realism** | KPI time-series generated via AR(1) state machines | Real network KPIs have diurnal patterns, seasonal effects, and event-driven spikes that AR(1) may underrepresent | Implement empirical distribution sampling from reference datasets |
| **Alarm correlation chains** | Synthetic cross-domain cascades may oversimplify real propagation delays | Model may expect instantaneous cascading when real propagation has variable latency | Add configurable propagation delay profiles per domain boundary |
| **CMDB degradation patterns** | Synthetic divergence may not reflect actual CMDB decay rates | Dark Graph detection tuned to synthetic decay rates may miss slower real-world drift | Calibrate degradation rates against published CMDB audit statistics |

### Pedk.ai Integration Points

| Pedk.ai Component | Fed By |
|-----------------|--------|
| `KPIMetricORM` / `KpiSampleORM` | Wide-format KPI Parquet files |
| `NetworkEntityORM` | `cmdb_declared_entities.parquet` |
| `EntityRelationshipORM` | `cmdb_declared_relationships.parquet` |
| `CustomerORM` / `BillingAccountORM` | `customers_bss.parquet` (future) |
| Alarm ingestion API (TMF642) | `events_alarms.parquet` |
| Dark Graph scoring | `divergence_manifest.parquet` + ground truth files |

---

## 11. TMF Standards Compliance

### TMF642 — Alarm Management API

- Standardised exposure of decision traces as network alarms
- Dual-correlation IDs: `external_correlation_id` (vendor NMS) and `internal_correlation_id` (Pedk.ai RCA)
- Alarm lifecycle: `raised` → `acknowledged` → `cleared`
- OAuth2 scope-based access enforcement

### TMF628 — Performance Management API

- Standards-compliant KPI exposure (throughput, latency, PRB utilisation)
- PerformanceMeasurement and IndicatorSpec Pydantic models

### Multi-Vendor Ingestion

| Vendor | Format | Ingestion |
|--------|--------|-----------|
| Ericsson (ENM) | XML alarms | Kafka + REST, `pm` prefix PascalCase counters |
| Nokia (NetAct) | JSON alarms | High-volume Kafka, `VS.` dot-separated hierarchy |
| Generic SNMP | Standard traps | Kafka consumer |

Alarm Normaliser: Pluggable strategy-based layer translating vendor payloads into unified internal signal format.

---

## 12. Deployment Model

### Infrastructure

| Component | Specification |
|-----------|---------------|
| API | FastAPI on Python 3.11+, multi-stage Docker container (non-root) |
| Database | PostgreSQL + JSONB + pgvector + TimescaleDB extension |
| Streaming | Apache Kafka |
| Container orchestration | Kubernetes with Helm charts |
| Secrets | Environment-injected; K8s Secrets template; TLS/SSL for DB |

### Deployment Modes

| Mode | Purpose | Data Access |
|------|---------|------------|
| **Offline PoC** | Day 1 wedge: historical data analysis, Divergence Report generation | Read-only. Customer provides CMDB snapshot, telemetry time-series, and ITSM ticket archive. Zero production access required. |
| **Shadow Mode** | Parallel-run alongside existing tools; proves accuracy without taking control | Read-only production data feeds (Kafka tap, syslog mirror). No write access to any system. |
| **Advisory Mode** | Generates SITREPs and recommendations alongside L2 workflows | Read-only production feeds + advisory output to NOC dashboard. No automated actions. |
| **Assisted Mode** | Creates draft tickets, pre-populates fields; operator approves every action | Read + limited write (ITSM draft creation). Operator approval gating. |
| **Production** | Full deployment with operator-selected autonomy level (see §7) | Read + write per customer policy. All actions audited. |

---

## 13. Security Model

### Authentication & Authorisation

- JWT-based authentication with signature verification
- Hierarchical RBAC: Admin → Operator → Viewer
- OAuth2 scopes per API domain
- Functional `/api/v1/auth/token` endpoint

### Data Protection

- Multi-tenant isolation: all queries scoped by `tenant_id` (§9)
- GDPR consent enforcement for proactive customer communications
- Data sovereignty guardrails: configurable data residency and egress controls
- Sensitive data scrubbing before external LLM provider calls

### Day 1 Trust Architecture

> [!IMPORTANT]
> **BSS integration (revenue, billing, customer PII) is explicitly deferred to a future roadmap milestone.** Pedk.ai's Day 1 deployment accesses only operational data: CMDB snapshots, alarm histories, ticket exports, and PM counters. This is deliberate — asking for BSS data before earning trust is a recipe for rejection. Walk before we run.

The trust progression:
1. **Day 1**: Read-only CMDB + historical tickets → Divergence Report (zero risk)
2. **Month 3**: Read-only production telemetry feeds → Shadow Mode (zero risk)
3. **Month 6**: Advisory Mode with SITREP generation → Operator trust established
4. **Month 12+**: BSS integration discussion only after proven value delivery

### Regulatory Compliance

| Framework | Document | Status | Action Required |
|-----------|----------|:------:|-----------------|
| OFCOM | Pre-notification document | ❌ Stub | Substantive rewrite required — must cover architecture, risk analysis, vendor compatibility |
| ICO | Data Protection Impact Assessment | ❌ Stub | Full DPIA covering data flows, retention periods, consent mechanisms, international transfers |
| Safety | Autonomous Safety Whitepaper | ❌ Stub | Architecture safety analysis, failure modes, testing methodology, rollback procedures |
| Autonomy | Status Report | ❌ Stub | Operational status template for ongoing autonomous action reporting |
| Internal | ADR-001 (Autonomy Positioning) | ✅ Complete | — |
| Internal | ADR-002 (Autonomous Execution Architecture) | ✅ Complete | — |

> [!CAUTION]
> **Regulatory documents are currently stubs.** This is a critical gap. No customer engagement with OFCOM-regulated operators can proceed until these documents contain substantive content. This is a top-priority task item.

---

## 14. Erdos Lens Analysis

This section applies the **Erdos AI Enterprise AI Deployment Methodology** three-lens analysis.

### Pedk.ai's Committee Review Cycle

Before the Erdos analysis, it is worth noting the rigorous review process Pedk.ai has already undergone. The product was subjected to a **multi-phase committee review cycle** involving:

- **Forensic Technical Auditor** (Pass 1): Line-by-line codebase audit against roadmap intent
- **Architecture Viability Review** (Pass 2): Structural integrity, design patterns, scale readiness
- **Adversarial Review** (Pass 3): Red-team perspective on claims vs evidence
- **Five-member executive committee**: Ops Director, CEO, Strategist, Enterprise Architect, QA Director
- **Formal remediation cycle**: 46 tasks identified across 6 phases, tracked in `3PassReviewOutcome_Roadmap_V3.yaml`

This review cycle resulted in the formal architecture review document (`ARCHITECTURE_S3_REMEDIATION.md.resolved`) which identified 6 Critical, 9 High, 10 Medium, and 4 Low findings — all with concrete remediation plans. The committee process itself is a product quality signal: Pedk.ai builds iteratively and subjects itself to structured criticism.

### Lens 1 — Product Readiness

| Dimension | Score | Rationale | Improvement Task |
|-----------|:-----:|-----------|-----------------|
| **Problem & Value** | 4 | Problem is specific, measurable (MTTR, CMDB accuracy), urgently felt. Stable over time. Clear ROI. | — |
| **Desired AI Behaviour** | 3 | AI role (advisory → gated autonomous) defined. Escalation boundaries exist. Safe fallback specified. | T-002: Formalise behaviour specification per autonomy level |
| **Human–AI Workflow** | 3 | NOC SITREP + acknowledge cycle implemented. Override tracking exists. | T-003: Implement behavioural observation feedback pipeline (§7) |
| **Data & Knowledge** | 3 | Multi-source strategy defined. Synthetic pipeline complete. Real data access limited. | T-004: Improve synthetic data realism (§10) |
| **Evaluation & Metrics** | 3 | Decision memory benchmark (0.9 threshold). Causal AI validated. | T-005: Implement continuous evaluation pipeline |
| **Safety & Governance** | 2 | Harm scenarios identified. Audit trail exists. **Regulatory docs are stubs.** | T-006: Write substantive OFCOM, ICO, Safety documents |
| **Learning & Feedback** | 3 | RLHF with multi-operator voting. Drift detection exists. | T-007: Implement structured multi-dimensional feedback (§7) |

**Product Readiness Score: 21/35 — Pilot Ready**

### Lens 2 — Enterprise AI Business Case

| Dimension | Score | Rationale | Improvement Task |
|-----------|:-----:|-----------|-----------------|
| **Operationalisation** | 2 | Runs in development. Structured logging, health probes implemented. In-process state won't survive scale-out. | T-008: Implement persistent event bus (Redis-backed queue) |
| **Decision Integration** | 3 | SITREPs inform NOC decisions. Policy engine gates actions. | T-009: Prove advisory value in real deployment scenario |
| **Risk & Accountability** | 2 | Owners defined. Acceptable error thresholds partially established. **Regulatory docs are stubs.** | T-006 (shared): Regulatory documentation |
| **Capability Building** | 2 | Training curriculum drafted. NOC runbook exists. Not tested with real operators. | T-010: Validate training curriculum with pilot NOC team |
| **Strategic Direction** | 3 | Clear vision (intelligence fabric). Competitive moat identified (Dark Graph + Abeyance Memory). | — |

**Business Case Score: 12/25 — Tool Adoption**

### Lens 3 — Skills & Workforce Readiness

| Dimension | Score | Rationale | Improvement Task |
|-----------|:-----:|-----------|-----------------|
| **Role Transformation** | 2 | NOC engineer supervisory role defined conceptually. | T-011: Define AI-adjusted NOC engineer role spec |
| **Skill Acquisition** | 2 | Training curriculum exists but untested. | T-012: Build hands-on training environment with synthetic data |
| **Collaboration Skills** | 1 | SITREPs are shared artefacts. No cross-team coordination protocol. | T-013: Design cross-team SITREP escalation workflow |
| **Knowledge Integration** | 2 | Decision Memory captures learnings. No playbook generation from patterns. | T-014: Implement automated playbook generation from high-confidence patterns |
| **Learning Culture** | 1 | Experimentation within dev team only. | T-015: Create "Pedk.ai Learning Hub" operator-facing knowledge base |

**Skills Readiness Score: 8/25 — Tool Adoption**

### Composite Readiness & AI Failure Pattern Mitigation

| Lens | Score | Band |
|------|:-----:|------|
| Product | 21/35 | **Pilot Ready** |
| Business Case | 12/25 | Tool Adoption |
| Skills | 8/25 | Tool Adoption |

> [!WARNING]
> **Erdos AI Failure Pattern**: The most common failure is **Behaviour maturity > Workflow maturity > Governance maturity** — the AI works, but the product doesn't. Pedk.ai exhibits this pattern: AI capabilities are ahead of operational workflow integration and governance maturity.

**Realistic mitigations the product team can take:**

| # | Mitigation | Targets | Priority |
|---|-----------|---------|:--------:|
| 1 | **Ship advisory-only first.** Resist the temptation to demonstrate autonomous capability. Focus every demo on SITREP quality and Dark Graph discovery. | Workflow gap | 🔴 Critical |
| 2 | **Write the regulatory documents.** OFCOM pre-notification, ICO DPIA, and Safety Whitepaper must be substantive before any operator engagement. | Governance gap | 🔴 Critical |
| 3 | **Implement behavioural feedback.** The highest-value learning signal is what operators *do*, not what they click. Invest here before expanding automation. | Workflow gap | 🔴 Critical |
| 4 | **Build the training environment.** An untested training curriculum is not a curriculum. Build hands-on exercises using synthetic data from Sleeping-Cell-KPI-Data. | Skills gap | 🟡 High |
| 5 | **Validate on reference deployment.** The committee review cycle was rigorous but internal. The next gate must involve a real NOC team. | Business case gap | 🟡 High |
| 6 | **Separate "works in demo" from "works in production."** Audit every feature for production-readiness. Honest maturity assessment (§6) is the first step. | Product gap | 🟡 High |

---

## 15. Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Backend API** | Python 3.11+, FastAPI | ML ecosystem, async-native |
| **Decision Store** | PostgreSQL + JSONB | Flexible schema, industry standard |
| **Time-Series** | TimescaleDB (Postgres extension) | Same engine, auto-partitioning |
| **Vector Search** | pgvector | Semantic similarity for decision traces and Abeyance Memory |
| **Streaming** | Apache Kafka | Industry standard for telemetry ingestion |
| **ML/AI** | PyTorch, scikit-learn, statsmodels | Anomaly detection, causal inference |
| **LLM** | **Vendor-neutral** — supports cloud-hosted (Gemini, GPT, Claude) and local/on-prem models (LLaMA, Mistral) via abstraction layer | Explanation layer, SITREP generation. Local LLM option critical for data sovereignty. |
| **Frontend** | Next.js | NOC dashboard SPA |
| **Containers** | Docker (multi-stage, non-root) | Production-hardened |
| **Orchestration** | Kubernetes + Helm | Scalable deployment |
| **Observability** | OpenTelemetry, structured JSON logging | Distributed tracing |
| **Testing** | pytest, Locust | Functional, integration, load |

> [!NOTE]
> **LLM vendor neutrality is a product requirement.** Pedk.ai's `LLMService` uses an abstraction layer that routes to the configured provider. Customers deploying on-premises with data sovereignty constraints can use local models. Cloud-hosted deployments can use any major provider. The product must never depend on a single LLM vendor.

---

## 16. Implementation Phases & Maturity Assessment

### Foundation & Signal Fabric (Phases 1–4) ✅

✅ Multi-tenant FastAPI backend, multi-database support, ingestion pipeline, Decision Trace schema, pgvector similarity search, anomaly detection, RCA engine, LLM SITREPs, sleeping cell detection, structured logging, health probes, circuit breakers, pytest suite, Docker.

### Intelligence & Standards (Phases 5–8) ✅

✅ Granger Causality, RLHF operator feedback, ADF stationarity tests, multi-operator feedback, memory optimisation, TMF642 Alarm API, TMF628 Performance API, vendor normaliser.

### Enterprise Excellence (Phases 9–11) ✅

✅ Committee review cycle (3-pass + 5-member executive), JWT auth, RBAC, TLS/SSL, Kubernetes manifests, OTel tracing, NOC dashboard.

### Expansion (Phases 12–14) ✅

✅ Memory benchmarking, capacity planning wedge, CX intelligence wedge.

### AI Control Plane (Phase 15+) ⚠️ Prototype

Policy engine, semantic context graph, RL evaluator. BSS data layer deferred to future roadmap.

### Structural Remediation (V8) 🔨 In Progress

46 tasks across 6 phases from formal architecture review.

### Dark Graph V8 🔨 In Progress

Full topology reconciliation across all divergence types, with CasinoLimit/Datagerry proving ground.

---

## 17. Governance & Quality Standards

### Erdos Quality Bar

| Element | Condition | Status | Action |
|---------|-----------|:------:|--------|
| Problem Statement | Specific, measurable, owned | ✅ Pass | — |
| Architecture | Clear layers, extensibility | ✅ Pass | — |
| Data Pipeline | Schema contracts, governing | ✅ Pass | — |
| Evaluation | Production monitoring, business linkage | ⚠️ Partial | T-005: Continuous evaluation pipeline |
| Safety & Governance | Enforced controls, continuous monitoring | ⚠️ Partial | T-006: Regulatory documents |
| Regulatory | Substantive, regulator-ready | ❌ Fail | T-006: OFCOM, ICO, Safety Whitepaper |
| Abeyance Memory | Persistent, long-horizon, multi-modal | ⚠️ Partial | T-016: Abeyance decay and cold storage |
| Evidence Fusion | Pluggable, per-customer | ⚠️ Partial | T-017: FusionMethodologyFactory |
| Operator Feedback | Behavioural + structured + quick | ⚠️ Partial | T-003, T-007: Feedback pipeline |
| Synthetic Data Quality | Realistic naming, scenarios, temporal patterns | ⚠️ Partial | T-004, T-018–T-022 |

### Task Backlog

| ID | Task | Priority | Project |
|----|------|:--------:|---------|
| **T-002** | Formalise AI behaviour specification per autonomy level (§7) | 🟡 High | Pedk.ai |
| **T-003** | Implement behavioural observation feedback pipeline — ingest operator ITSM actions as learning signal | 🔴 Critical | Pedk.ai |
| **T-004** | Improve synthetic data realism: temporal patterns, propagation delays, CMDB decay calibration | 🔴 Critical | Sleeping-Cell-KPI-Data |
| **T-005** | Implement continuous evaluation pipeline with business outcome linkage | 🟡 High | Pedk.ai |
| **T-006** | Write substantive regulatory documents: OFCOM pre-notification, ICO DPIA, Safety Whitepaper, Autonomy Status Report | 🔴 Critical | Pedk.ai |
| **T-007** | Implement structured multi-dimensional operator assessment (accuracy, relevance, actionability) | 🟡 High | Pedk.ai |
| **T-008** | Implement persistent event bus (Redis-backed queue) to replace asyncio.Queue | 🟡 High | Pedk.ai |
| **T-009** | Design and execute reference deployment scenario with advisory-only mode | 🟡 High | Pedk.ai |
| **T-010** | Validate training curriculum with pilot NOC team using synthetic data exercises | 🟡 High | Pedk.ai |
| **T-011** | Define AI-adjusted NOC engineer role specification | 🟢 Medium | Pedk.ai |
| **T-012** | Build hands-on training environment with Sleeping-Cell-KPI-Data | 🟢 Medium | Pedk.ai |
| **T-013** | Design cross-team SITREP escalation workflow | 🟢 Medium | Pedk.ai |
| **T-014** | Implement automated playbook generation from high-confidence Decision Memory patterns | 🟢 Medium | Pedk.ai |
| **T-015** | Create operator-facing "Pedk.ai Learning Hub" knowledge base | 🟢 Medium | Pedk.ai |
| **T-016** | Implement Abeyance Memory decay scoring and cold storage retrieval pipeline | 🔴 Critical | Pedk.ai |
| **T-017** | Implement `FusionMethodologyFactory` — pluggable evidence fusion (Noisy-OR, Dempster-Shafer) | 🟡 High | Pedk.ai |
| **T-018** | Replace UUID V4 identifiers with operator-realistic human-friendly naming conventions | 🔴 Critical | Sleeping-Cell-KPI-Data |
| **T-019** | Validate synthetic fault scenarios against published Tier-1 post-incident reports | 🟡 High | Sleeping-Cell-KPI-Data |
| **T-020** | Implement diurnal/seasonal temporal patterns in KPI generation (beyond AR(1)) | 🟡 High | Sleeping-Cell-KPI-Data |
| **T-021** | Add configurable propagation delay profiles per domain boundary for cascading alarms | 🟡 High | Sleeping-Cell-KPI-Data |
| **T-022** | Calibrate CMDB degradation rates against published CMDB audit statistics | 🟡 High | Sleeping-Cell-KPI-Data |
| **T-023** | Implement causal inference methodology selection: add Transfer Entropy and PCMCI alternatives | 🟡 High | Pedk.ai |
| **T-024** | Wire sleeping cell detector into `main.py` scheduler (currently dead code) | 🔴 Critical | Pedk.ai |
| **T-025** | Strengthen Dark Graph module: complete Divergence Report, Datagerry adapter, CasinoLimit parser | 🔴 Critical | Pedk.ai |
| **T-026** | Implement Abeyance Memory multi-modal matching (structured telemetry ↔ unstructured text) | 🟡 High | Pedk.ai |
| **T-027** | Frontend decomposition: split monolithic `page.tsx` into routed pages | 🟡 High | Pedk.ai |
| **T-028** | Phase 5 test suite: expand from ~5 trivial tests to comprehensive safety gate coverage | 🟡 High | Pedk.ai |

---

## 18. Document Catalogue

### Archived (moved to `docs/archive/`)

All superseded root-level documents — see archive directory for full inventory. Key categories:
- Vision documents (V3, V8, alignment reports)
- Implementation roadmaps (V1–V4, agentic plans)
- Executive reviews and committee assessments (6+ versions)
- Phase completion summaries
- Strategic audits and remediation plans
- Sales and marketing drafts

### Retained in Project Root

| Document | Purpose |
|----------|---------|
| `PRODUCT_SPEC.md` | **This document** — single source of truth |
| `README.md` | Developer onboarding and quick start guide |
| `CONSTRAINTS.md` | Operational constraints |
| `ARCHITECTURE_S3_REMEDIATION.md.resolved` | Active remediation tracker (46 tasks, 6 phases) |

### Retained in `docs/`

| Document | Purpose |
|----------|---------|
| `TASKS.md` | Active task backlog |
| `IMPLEMENTATION_ROADMAP_V8.md` | Active Dark Graph V8 blueprint |
| `ADR-001-autonomy-positioning.md` | Architecture Decision Record |
| `ADR-002-autonomous-execution-architecture.md` | Architecture Decision Record |
| `service_inventory.md` | Service module inventory |
| `noc_runbook.md` | NOC operations runbook |
| `training_curriculum.md` | Operator training curriculum |
| `value_methodology.md` | ROI value methodology |
| `shadow_mode.md` | Shadow mode deployment spec |
| `TELCO2_*.md` | Active Telco2 integration docs |
| `3PassReviewOutcome_Roadmap_V*.yaml` | Active remediation backlog (machine-readable) |

### Candidates for Merge

The following `docs/` files contain overlapping content and should be consolidated in a future pass:

| Files | Merge Into |
|-------|-----------|
| `confidence_methodology.md` + `ai_maturity_ladder.md` | This document (§5, §14) |
| `data_architecture_adr.md` + `dpia_scope.md` | `ADR-003-data-architecture.md` (new) |
| `amendment_status_tracker.md` | `ARCHITECTURE_S3_REMEDIATION.md.resolved` (active tracker) |
| `GTM_DEMO_SUITE_V8.md` + `PEDKAI_PITCH_DECK_V8.md` + `PEDKAI_V8_EXECUTION_DEEP_DIVE.md` | Single `GTM_MATERIALS.md` |

---

*Pedk.ai — AI-Native Operational Reconciliation Engine*  
*Methodology: Erdos AI Enterprise AI Deployment Framework*  
*Synthetic Data: [Sleeping-Cell-KPI-Data](https://github.com/himan8pd/Sleeping-Cell-KPI-Data) Pipeline*
