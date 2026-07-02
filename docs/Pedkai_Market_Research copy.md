---
title: |
  \fontsize{30}{35}\selectfont pedk.ai --- AI-Native Operational Reconciliation Engine
subtitle: "Market Research Outcome --- Version 2.0"
author: |
  \fontsize{20}{22}\selectfont Himanshu Thakur
date: |
  \fontsize{16}{16}\selectfont May 2026
subject: "Market Research Output for BSE (Bombay Stock Exchange)"
keywords: [Reconciliation, Abeyance Memory, Dark Graph, pedk.ai, BSE, FMI, Market Infrastructure]
lang: "en"

geometry: "margin=2.2cm"

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

header-left: "pedk.ai --- Market Research Outcome v2.0"
header-right: "May 2026"
footer-left: "Confidential --- For BSE Discussion"
footer-right: "Page \\thepage"

titlepage: true
titlepage-color: "06203b"
titlepage-text-color: "FFFFFF"
titlepage-rule-color: "00D4FF"
titlepage-rule-height: 2
titlepage-logo: "pedkai_logo.jpeg"
logo-width: "260pt"

toc: true
toc-own-page: true
colorlinks: true
linkcolor: "cyan"
urlcolor: "cyan"
toccolor: "cyan"

fontsize: 10pt
caption-justification: centering
table-use-row-colors: true
---

# Executive Summary

> **pedk.ai is an AI-native operational reconciliation engine purpose-built for
> financial market infrastructure.** Its differentiator is *Abeyance Memory*:
> a persistent semantic memory that holds unresolved breaks, exceptions, and
> anomalies across settlement cycles --- and retroactively correlates them
> when new evidence arrives, days or weeks later.

**The reconciliation problem in FMI.** Every exchange, clearing house,
depository, and custodian runs on a fragmented stack: order-management, market data, clearing, settlement, and custody
ledgers. Reconciliation between these layers, between firms (broker ↔
clearing house ↔ depository ↔ bank), and across cycles (T, T+1, EOD,
corporate-action windows) produces a steady stream of *breaks* --- mismatches
that must be investigated, root-caused, and resolved. The exception items that
*do not* resolve inside a cycle linger as latent risk: financial-market
no-fault-found cases.

**What every incumbent does today.** Match-and-discard. Rule engines and
matching frameworks (Smartstream TLM, AutoRek, Duco, IntelliMatch, Broadridge, ServiceNow)
attempt to pair records inside a window; unmatched items go to a queue, where
they age until an analyst closes them manually or they expire silently. No
incumbent holds the *semantic content* of an unresolved break in a way that
can re-fire when a related event arrives weeks later. Existing AI/ML offerings
sit on top of the matching layer, not in place of the memory it lacks.

**What pedk.ai does differently.** Three architectural commitments:

1. **Abeyance Memory** --- unresolved breaks are stored as multi-dimensional
   fragments (semantic, topological, temporal, operational) with
   source-specific decay; *trade-break* and *settlement-exception* fragments
   carry the highest base relevance and the longest TTLs (up to 365 days for
   structural events like corporate actions, fee-schedule changes, or
   regulatory cut-overs).
2. **Shadow Topology** --- a discovered graph of the FMI estate (OMS, clearing
   engine, settlement platform, depository link, custodian feed, market-data
   sources) with provenance and confidence. Cross-system breaks are correlated
   via the topology, not via brittle text similarity.
3. **Sovereign Cloud model serving** --- All data is held on pedk.ai's PostgresSQL database VM on Oracle Cloud Infrastructure (OCI) in India. LLM used for inference runs on its own container using ollama on the pedk.ai app VM on OCI as well. This model aligns with SEBI requirements, RBI guidance, and the DPDPA framework.

**Why now, why BSE.** India is the highest-volume retail F&O market in the
world; settlement cycles are compressing (T+1 standardised, T+0 piloting);
SEBI has tightened surveillance and outage-reporting requirements; and
operational losses from break investigation, manual triage, and audit response
are growing faster than headcount can absorb. BSE has the scale, the
regulatory mandate, and a technology renewal cycle that makes it a natural
anchor for an AI-native reconciliation platform built in India, served
locally, and standards-aligned (FIX, ISO 20022, FpML on the roadmap).

**Single most important recommendation.** Anchor a 90-day pilot at BSE on a
single, painful reconciliation surface (we recommend post-trade allocation /
custodian-side settlement breaks, where unresolved items routinely span
multiple T-cycles). Measure two KPIs: (i) reduction in unresolved-break
inventory at end of day; (ii) cross-cycle retroactive correlations not
findable by existing tooling. If both move, expand horizontally to corporate
actions, F&O margin reconciliation, and SLB.

# The Reconciliation Problem in FMI

Financial market infrastructure is a layered stack in which every system ---
OMS, clearing engine, settlement platform, depository link, custodian feed,
market-data sources, the firm ledger --- records its own version of the same
economic event. Reconciliation proves those versions agree, across the
front-middle-back office of a single firm, between firms (broker ↔ clearing
member ↔ CCP ↔ depository ↔ custodian ↔ bank), and across cycles (intraday,
EOD, T+1, T+0, corporate-action windows).

The pain is structural: fragmented record-keeping across schemas, multi-protocol
data (FIX, ISO 20022, FpML, SWIFT MT/MX, exchange-proprietary, custodian flat
files), inter-firm dependencies, compressed settlement windows (T+1 standard,
T+0 piloting in India), corporate-action shocks that surface days later, and
*no-fault-found* exceptions that close manually with no recorded root cause.

**The "abeyance" pattern.** A material share of operational pain comes from
breaks whose root cause lives *outside* the cycle in which they appear:

- A **late corporate action** posted on T+3 causes settlement under-deliveries
  on T+5 trades, surfacing in custody recon on T+7.
- A **stale market-data tick** seeds a mark-to-market drift, detected days
  later as a P\&L vs. clearing-margin discrepancy.
- A **fee-schedule change** silently shifts gross/net allocations for a
  segment of members; the cumulative break is noticed at month-end.
- A **counterparty re-mapping** (CSD change, custodian merger) causes
  intermittent SSI breaks that recur over weeks.

Existing reconciliation platforms are excellent at *matching what they see in
the window*. They are not built to *hold and re-evaluate* what they could not
match. That is the gap pedk.ai is designed to close --- driven by signals
that all point the same way: India retail F\&O volumes at record levels,
T+0 expansion under SEBI review, the 2025 SEBI tech-resilience framework
tightening outage and surveillance reporting, and DPDPA creating a hard
local-data-processing constraint that disqualifies cloud-only AI vendors.

# The pedk.ai Approach --- Abeyance Memory for FMI

## The three architectural commitments

**(a) Abeyance Memory.** Every break, exception, surveillance alert, or
operational anomaly is ingested as a *fragment* with four independent
embeddings:

| Embedding column   | Dimension  | What it captures                                                                              |
|--------------------|------------|------------------------------------------------------------------------------------------------|
| Semantic           | 1536-d     | The textual content of the break (description, narrative, free-form fields)                    |
| Topological        | 1536-d     | The 2-hop neighbourhood in the Shadow Topology (which systems, segments, counterparties)       |
| Temporal           | 256-d      | Sinusoidal time encoding (cycle position, time-of-day, weekday, near-cut-off windows)          |
| Operational        | 1536-d     | Operational fingerprint (severity, queue, owner team, recurrence)                              |

Fragments carry a *base relevance* and *decay constant* tuned per source type:

| Source type (FMI mapping)                                       | Base relevance | Decay τ (days)              |
|-----------------------------------------------------------------|----------------|-----------------------------|
| Free-text exception / NFF break (analyst narrative)             | **0.9**        | 270                         |
| Settlement / trade-break alert                                  | 0.7            | 90                          |
| Telemetry event (intraday metric, latency, queue depth)         | 0.6            | 60                          |
| Operator action / CLI / system log                              | 0.7            | 180                         |
| Configuration / fee-schedule / corporate-action change record   | 0.8            | **365** (longest)            |
| Reference-data / CMDB delta                                     | 0.7            | 90                          |

A *near-miss boost* of **1.15×** is applied to fragments that almost matched a
prior candidate; over many cycles, the system surfaces correlations that no
single window contained.

**(b) Shadow Topology.** A discovered, confidence-scored graph of the FMI
estate: trading systems, clearing engine, settlement platform, depository
links, custodian feeds, market-data sources, and the dependency edges between
them. The graph is built by entity resolution across the ingested fragments
themselves --- it is not a hand-curated CMDB and not a vendor-supplied
schematic. Two-hop expansion at query time lets the snap engine compare
fragments by *topological neighbourhood*, not just text.

**(c) Local model serving.** T-VEC embeddings run on CPU (~3 GB);
hypothesis-generation runs on a quantised domain LLM (TSLAM-Mini-2B, Q4\_K\_M)
served via Ollama on a single GPU. Zero cloud egress, zero per-call inference
cost. SEBI / RBI / DPDPA-aligned by construction.

## Snap Engine --- the cross-domain matching kernel

The Snap Engine evaluates candidate pairs of fragments across five weighted
dimensions: semantic, topological, temporal, operational, and entity overlap.
A Sidak correction controls false-positive rate as candidate counts grow. The
five weight profiles correspond to five failure-mode families pedk.ai targets
first (dark edge, dark node, identity mutation, phantom CI, dark attribute);
profiles are calibrated per customer once 500+ labelled outcomes accumulate.

For FMI, this means a "dark edge" snap can connect a corporate-action change
record (with 365-d TTL) to a custody settlement break (with 90-d TTL) via
their shared topological neighbourhood, even when their text descriptions
share no vocabulary.

# Competitive Landscape

**Direct reconciliation incumbents.** The major FMI reconciliation platforms
are **Smartstream TLM** (mature transaction-lifecycle engine; rule + ML
matching, cloud + on-prem), **Duco** (modern data-agnostic SaaS with strong UX
and AI-assisted matching, but SaaS-only --- friction with India's
data-localisation posture), **AutoRek** (financial-services focus, mostly
on-prem, limited AI surface), **IntelliMatch / FIS** (broad asset-class
coverage on a legacy architecture), **Gresham Clareti** (real-time recon
control framework), **Broadridge post-trade** (recon as one module of a large
processing platform), **AccessFintech Synergy** (industry network for break
*workflow*, adjacent rather than competitive), and **TCS BaNCS** (the platform
in use at BSE; recon is a module rather than the focus). None of these holds
unresolved breaks as semantic fragments for retroactive cross-cycle
correlation.

**Adjacent IT-operations platforms.** **ServiceNow** (ITSM + ITOM + agent
memory) is the highest long-term threat: it owns the ticket layer at many
FMIs and could, in principle, add latent-evidence retention to its agent
memory. **BMC Helix** is similar to ServiceNow. Generalist AIOps tools (Dynatrace, Splunk, Datadog)
solve the infrastructure-metrics problem, not the business-event
reconciliation problem so while they are noted, we do not consider them direct competitors for pedk.ai.

## Capability Comparison with FMI Reconciliation Platforms

| Capability                                             | \rothead{TLM}    | \rothead{Duco}   | \rothead{AutoRek} | \rothead{IntelliMatch} | \rothead{Broadridge} | \rothead{ServiceNow} | **pedk.ai**                    |
|--------------------------------------------------------|--------|--------|---------|--------------|------------|------------|--------------------------------|
| Rule-based matching                                    | ✓      | ✓      | ✓       | ✓            | ✓          | (ITSM only) | ✓                              |
| ML-augmented matching                                  | ✓      | ✓      | partial | partial      | partial    | partial    | ✓                              |
| Latent-evidence retention across cycles                | --     | --     | --      | --           | --         | --         | **✓ (unique)**                 |
| Multi-modal embedding fusion (sem+topo+temp+ops)       | --     | --     | --      | --           | --         | --         | **✓**                          |
| Discovered topology with provenance                    | --     | --     | --      | --           | --         | CMDB-overlay | **✓ (Shadow Topology)**       |
| Closed-loop weight optimisation (Bayesian, per-tenant) | --     | --     | --      | --           | --         | --         | **✓ (Outcome Calibration)**    |
| LLM-grounded hypothesis generation                     | --     | partial| --      | --           | --         | LEAP-style | **✓ (Phi4-Mini)**               |
| Local-only model serving (no cloud egress)             | --     | --     | partial | partial      | --         | --         | **✓**                          |
| FMI-specific by design                                 | ✓      | ✓      | ✓       | ✓            | ✓          | --         | **✓**  						   |

## Capability Comparison with ServiceNow (Service Management Reconciliation)

**How they do it (technically):**

ServiceNow's AIOps operates through multiple technical layers:

**Alert Correlation (RAMC Framework)** -- prioritized sequence:
1. **Rule-Based (R)**: Custom filters, scripts, CI relationships with configurable time windows (e.g., 60-minute intervals)
2. **Automated (A)**: ML/AI patterns from historical alert data for same CI/metric combinations. Uses "aggregation algorithms that rely on historical alerts with the same alert identifier (CI and metric identifier) and which occurred multiple times in the same time frame"
3. **Manual (M)**: Operator parent-child assignment
4. **CMDB (C)**: Groups based on CI relationships in CMDB

**How Abeyance Memory compares:**

| Capability | ServiceNow | Abeyance Memory 3.0 | Assessment |
|---|---|---|---|
| **Correlation approach** | RAMC (rule -> automated -> manual -> CMDB). Automated requires *same CI/metric* recurring in *same timeframe* | Snap Engine: 5-dimension weighted scoring (semantic, topological, temporal, operational, entity overlap) with mask-aware redistribution. Can correlate *different* descriptions of *same* problem across domains | **AM stronger for novel correlations**: ServiceNow finds patterns it has seen before. AM finds patterns nobody has seen before through semantic/topological fusion |
| **Anomaly detection** | MAD, Kalman, time-series, non-parametric -- mature, well-tested statistical stack | Surprise Engine (Mechanism 1): adaptive histogramming of snap score distributions per (tenant, failure_mode_profile), threshold starts at 99.99th percentile | **ServiceNow broader**: More statistical methods. AM's surprise engine is narrower but operates on snap scores (multi-dimensional correlation output) rather than raw metrics |
| **RCA** | 5 correlation algorithms (conditional probability, Levenshtein fuzzy matching, K-means, temporal, entity extraction) | Hypothesis Generation (TSLAM-8B falsifiable claims) + Expectation Violation (transition matrix statistical test) + Causal Direction Testing (temporal ordering consistency) | **Different paradigms**: ServiceNow uses statistical correlation. AM uses LLM-generated hypotheses validated by causal testing. AM is more ambitious but less proven |
| **Long-term memory** | LEAP mines 6 months of incident resolution notes. Knowledge Graph references CMDB. "Persistent memory" in agents but unspecified | Fragments retained 60d (telemetry) to 730d (changes) in hot/warm storage, 1095d before deletion. Cold storage with ANN search. Source-specific decay curves | **AM deeper and more structured**: ServiceNow's 6-month window is fixed and incident-only. AM retains diverse evidence types with source-specific decay and near-miss boosting |
| **Cross-domain semantic gap** | K-means text clustering + Levenshtein fuzzy matching -- limited ability to connect different vocabulary describing the same failure | 4-column embeddings: topology-aware T-VEC encoding ensures "high BLER on cell 8842-A" and "CRC errors on S1 bearer" are compared via topological neighborhood, not just text similarity | **AM significantly stronger**: This is Abeyance Memory's core innovation |
| **Ecosystem/distribution** | Massive installed base. CMDB already deployed at most Tier-1 operators. ITSM workflow integration native | Standalone platform requiring integration | **ServiceNow dominant**: Distribution advantage is overwhelming. Must integrate with, not compete against |
| **Data quality** | Security concern noted: "Knowledge Graph does leak information that should not be available for the user based on ACLs" | Tenant isolation (INV-7), dedup keys, validated schema (INV constraints) | **AM more rigorous**: Multi-tenant security is architecturally enforced |


# Engagement Plan for BSE

## What pedk.ai Does

pedk.ai is an intelligence fabric that sits between your existing systems --- monitoring platforms, ITSM tools, asset registers, change management systems --- and tells you the truth about your technology estate. It cross-correlates what your systems *actually do* (operational telemetry) against what your organisation *thinks* they do (asset register) and what your engineers *actually know* (incident and change ticket patterns).

pedk.ai **augments** your existing tools. It does not replace your monitoring platform, your ITSM system, or your asset register. They do what they're designed to do. pedk.ai adds the reconciliation layer they've never had.

pedk.ai already integrates with **ServiceNow** --- polling incidents, correlating operator actions with AI recommendations, and computing behavioural feedback to improve over time. Your existing ServiceNow investment becomes more valuable, not redundant.

## How It Works --- Day 1

pedk.ai requires no production access on Day 1. No write access to any system. No sensitive data. No market data. No trading information.

You provide three read-only historical datasets:

| What You Share | What It Contains | What pedk.ai Finds |
|----------------|------------------|-------------------|
| **Asset Register** | Your technology assets and their declared dependencies | The "documented truth" --- what you think your infrastructure looks like |
| **Monitoring History** | 3--12 months of system metrics, event logs, alert records | The "operational truth" --- what your infrastructure actually did |
| **Ticket Archive** | Incident and change ticket history | The "human truth" --- how your engineers actually fix problems |

In response, pedk.ai delivers a **Divergence Report**:

- Systems generating telemetry with no asset register record (**shadow IT** --- untracked, unpatched, unmonitored)
- Registered assets with zero operational footprint for months (**phantom systems** consuming licences and compute)
- Hardware/VM replacements detected from telemetry mismatches (**identity mutations** --- the register says Server A, but Server A was replaced by Server B six months ago)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns (**hidden single points of failure**)

**Zero risk. Zero disruption. Proven value before any deeper conversation.**