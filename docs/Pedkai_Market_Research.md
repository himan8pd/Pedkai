---
title: |
  \fontsize{30}{35}\selectfont pedk.ai --- AI-Native IT-Operations Reconciliation Engine
subtitle: "Market Research Outcome --- Version 2.1"
author: |
  \fontsize{20}{22}\selectfont Himanshu Thakur
date: |
  \fontsize{16}{16}\selectfont May 2026
subject: "Market Research Output for BSE (Bombay Stock Exchange)"
keywords: [AIOps, IT-Operations Reconciliation, CMDB Reconciliation, Abeyance Memory, Shadow Topology, pedk.ai, BSE, FMI, Market Infrastructure]
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

header-left: "pedk.ai --- Market Research Outcome v2.1"
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

> **The AIOps and IT-operations reconciliation software market is a large,
> rapidly consolidating category driven by three forces: regulatory pressure
> on operational resilience, the agent-and-LLM inflection inside every
> incumbent's roadmap, and data-sovereignty regimes that increasingly
> disqualify cloud-only foreign vendors in regulated geographies. This
> document maps the vendor landscape, the forces shaping it, and the
> capability gaps most relevant to an Indian financial-market-infrastructure
> (FMI) operator.**

**Market shape:** 

AIOps is among the fastest-growing categories in enterprise
IT software --- Gartner sizes the AIOps platform market at roughly USD
2--3B in 2025 with mid-teens CAGR, sitting inside the much larger ITOM
(USD 30B+) and observability (USD 50B+) categories. For a tier-1 FMI
operator, the relevant capability surface spans four functions:
*discovery* (what is in my estate?), *observability* (what is it doing
right now?), *event correlation / AIOps* (what is the root cause?), and
*service management* (who is fixing it, on what SLA?). These functions
historically lived in separate tools; the market is now consolidating into
bundled suites.

**Vendor archetypes:**

1. *Integrated ITSM + ITOM + AIOps suites.* ServiceNow (category leader;
   ITSM + Discovery + Service Mapping + AIOps + Now Assist) and BMC Helix
   (closest architectural cousin, with Helix Discovery widely regarded as
   best-in-class agentless discovery). Cover all four functions inside a
   single commercial relationship; strongest on workflow integration.
2. *Observability platforms with AIOps overlays.* Dynatrace (Davis AI on
   Smartscape topology), Splunk (ITSI + Observability Cloud + Splunk AI),
   Datadog (Watchdog), New Relic, LogicMonitor, ScienceLogic SL1,
   AppDynamics (Cisco). Strongest in telemetry depth; AIOps and topology
   layered on top.
3. *Event correlation and noise reduction.* BigPanda, Moogsoft (Dell),
   Netreo. Narrow scope: dedupe and correlate alerts between monitoring
   tools and ITSM. Deployed alongside, not instead of, the platforms above.
4. *Specialised discovery / CMDB reconciliation.* Device42, Faddom, Cisco
   Tetration / Secure Workload (network-flow-derived topology), VMware Aria.
   Strong at building topology; do not own the correlation, hypothesis, or
   workflow layers.

**Forces shaping the market:**

1. *Regulatory drumbeat on operational resilience.* SEBI's 2025
  tech-resilience framework, RBI operational-resilience guidance, EU DORA,
  US OCC outsourcing rules, and BCBS-239 all push toward auditable,
  demonstrable knowledge of the IT estate, its dependencies, and incident
  root cause. Outage-reporting timelines have tightened to hours, not days.
2. *CMDB inaccuracy at FMI scale.* Industry surveys (Gartner, Forrester,
  2023--2025) consistently put CMDB inaccuracy at 30--60% in tier-1
  enterprises. Shadow IT, phantom assets, identity mutations, and
  undocumented dependencies create audit exposure and incident risk that
  grow faster than ops headcount.
3. *The agent inflection.* Every major incumbent (ServiceNow Now Assist,
  BMC HelixGPT, Splunk AI Assist, Dynatrace Davis CoPilot, Datadog Bits AI)
  has shipped LLM agents in the past 18 months. None retain unresolved
  alerts or unconfirmed correlations as persistent semantic memory across
  cycles --- each incident is treated as a discrete unit. Analysts (Gartner,
  Forrester) flag persistent memory and cross-incident retroactive
  correlation as the next capability frontier.
4. *Data localisation.* India's DPDPA and analogous regimes progressively
  disqualify cloud-only foreign AIOps vendors for sensitive operational
  telemetry --- a structural headwind for SaaS-only incumbents and a
  tailwind for sovereign-hosted offerings.
5. *Indian FMI estate scale.* Indian exchanges run the world's highest
  contract-count volumes; the IT estate behind them spans 200--1000+
  applications across trading, clearing, settlement, depository,
  surveillance, risk, and reporting --- with multi-decade legacy alongside
  new microservices-based systems. Operational pain in this kind of estate
  is dominated by CMDB drift and undocumented dependency patterns, not by
  transaction-level processing.

**Where the market is under-served:** 

Three capability gaps are consistent across all vendor archetypes: 

1. no *persistent semantic memory* of unresolved correlations across cycles --- every incumbent correlates within
a window and discards what does not match; 
2. no *discovered, confidence-scored topology* independent of CMDB or agent instrumentation - vendors either trust the CMDB (which is stale) or build agent-only topologies (which miss what is not instrumented); 
3. no *local-only model serving* --- AI features are uniformly cloud-hosted, a structural disqualifier under DPDPA. Cost structures reinforce the gap: 5-year TCO for an integrated suite at FMI scale routinely lands in the USD 8--25M range, with implementation and customisation drag often matching license cost.

**Implications for BSE:** 

The Indian FMI procurement environment increasingly
favours (a) locally hosted or sovereign-cloud AIOps architectures, (b)
AI-native rather than AI-bolt-on platforms, and (c) modular plays that
augment existing ITSM and observability investment rather than replace it.
BSE is positioned to anchor a domestic, AI-native AIOps and operational-state
reconciliation capability that aligns with SEBI / RBI / DPDPA expectations and can be syndicated
across the wider Indian FMI ecosystem (depositories, CCPs, clearing members).

# The IT-Operations Reconciliation Problem in FMI

Financial market infrastructure runs on a deeply layered IT estate: trading
platforms, clearing engines, settlement systems, depository links, custodian
connectivity, market-data feeds, surveillance and risk engines, the
middleware and message buses that connect them, and the supporting
infrastructure (compute, network, storage, observability tooling) that keeps
them running. The estate spans on-prem datacentres, colocation, public cloud,
and SaaS --- often with multi-decade legacy alongside new microservices-based
systems --- and is operated by tightly siloed teams (trading-systems,
market-data, network, security, application-ops, database).

The reconciliation problem at this layer is not about financial transactions.
It is about proving that what an organisation *declares* about its IT estate
(in the CMDB, asset register, service catalogue) matches what the estate
*actually does* (telemetry, logs, network flows) and what its engineers
*actually know* (incident, change, and problem history). When these three
pictures diverge, the consequences are operational (mis-routed incident
response), regulatory (incomplete audit evidence), and financial in turn
(prolonged outages, SLA penalties, regulatory fines).

*The structural pain.* Industry surveys from Gartner and Forrester
(2023--2025) consistently put CMDB inaccuracy at 30--60% in tier-1
enterprises; the figure is typically worse in regulated environments where
change velocity outpaces the ability of ops teams to keep documentation
current. Specific failure patterns recur:

- *Shadow IT* --- systems generating telemetry, traffic, or log events with
  no corresponding CMDB record. Often spun up for short-term projects and
  never decommissioned; uninventoried, unpatched, unmonitored.
- *Phantom CIs* --- CMDB entries for systems with no operational footprint
  for months. Consuming licences, audit attention, and compute reservation;
  usually decommissioned without the CMDB being updated.
- *Identity mutations* --- the asset register names a host that was
  silently replaced (hardware refresh, VM rebuild, cloud-account migration)
  without re-baselining. The label persists; the underlying entity is
  different.
- *Dark edges* --- operational dependencies between systems that exist in
  production but appear nowhere in the service map. Usually surface only
  when a change in System A unexpectedly breaks System B.
- *Dark attributes* --- configuration parameters (kernel settings, JVM
  flags, feature flags, application-config entries) that drift from baseline
  silently and are not picked up by configuration management.

Existing AIOps and observability platforms are excellent at correlating
events *inside the window they see*. They are not built to *hold and
re-evaluate* what they could not correlate. That is the gap pedk.ai is
designed to close, in an FMI context shaped by signals that all point the
same way: SEBI's 2025 tech-resilience framework tightening outage and audit
reporting, RBI operational-resilience guidance, the DPDPA hard
local-data-processing constraint, and the agent inflection in AIOps that
every incumbent is now chasing.

# The pedk.ai Approach --- Abeyance Memory for FMI

## The three architectural commitments

*(a) Abeyance Memory.* Every break, exception, surveillance alert, or
operational anomaly is ingested as a *fragment* with four independent
embeddings:

| Embedding column   | Dimension  | What it captures                                                                              |
|--------------------|------------|------------------------------------------------------------------------------------------------|
| Semantic           | 1536-d     | The textual content of the break (description, narrative, free-form fields)                    |
| Topological        | 1536-d     | The 2-hop neighbourhood in the Shadow Topology (which systems, services, dependencies)         |
| Temporal           | 256-d      | Sinusoidal time encoding (cycle position, time-of-day, weekday, near-cut-off windows)          |
| Operational        | 1536-d     | Operational fingerprint (severity, queue, owner team, recurrence)                              |

A *near-miss boost* of *1.15×* is applied to fragments that almost matched a
prior candidate; over many cycles, the system surfaces correlations that no
single window contained.

*(b) Shadow Topology.* A discovered, confidence-scored graph of the FMI
estate: trading systems, clearing engine, settlement platform, depository
links, custodian feeds, market-data sources, and the dependency edges between
them. The graph is built by entity resolution across the ingested fragments
themselves --- it is not a hand-curated CMDB and not a vendor-supplied
schematic. Two-hop expansion at query time lets the snap engine compare
fragments by *topological neighbourhood*, not just text.

*(c) Local model serving.* T-VEC embeddings run on CPU (~3 GB);
hypothesis-generation runs on a quantised domain LLM (TSLAM-Mini-2B, Q4\_K\_M)
served via ollama in a container on pedk.ai application server. Zero cloud egress, zero per-call inference
cost. SEBI / RBI / DPDPA-aligned by construction.

# Competitive Landscape

The competitive landscape for pedk.ai sits inside the *AIOps and
IT-operations management* market. Vendors fall into four archetypes by
primary capability: integrated ITSM/ITOM/AIOps suites, observability
platforms with AIOps overlays, event-correlation and noise-reduction tools,
and specialised discovery / CMDB-reconciliation tools. Pedk.ai occupies a
position not directly held by any incumbent --- agentless discovered
topology with confidence scoring, plus persistent semantic memory of
unresolved correlations across cycles, fed by ingestion from existing tools
rather than by deploying new agents --- and competes asymmetrically with
each archetype on a different axis.

## The AIOps Vendor Landscape

### Tier 1 --- Integrated ITSM + ITOM + AIOps Suites

*ServiceNow* is the category leader. Its IT-operations stack pairs ITSM
(the ticket layer that owns incident, problem, change, and request
workflows) with ITOM Discovery and Service Mapping (which build the CMDB
and dependency graph), Event Management and AIOps (which correlate alerts
using a Rule-Automated-Manual-CMDB framework), and the Now Assist
LLM-agent layer (which summarises, recommends, and increasingly drafts
responses). At FMI scale, customers typically run all four components on a
single ServiceNow tenant, often integrating with two or three observability
tools below. Strengths: distribution, integration depth, full lifecycle
coverage. Weaknesses: AIOps correlation is intra-window and depends on
pattern recurrence (same CI / same metric / same time-frame); persistent
memory of unconfirmed correlations is roadmap rather than shipped; pricing
scales aggressively at FMI volume. 

>*Compared to pedk.ai:* ServiceNow is the most relevant single competitor and a probable integration partner. Pedk.ai differs on cross-cycle persistent abeyance memory, on confidence-scored discovered topology that does not depend on the CMDB being accurate, and on local-only model serving for sovereign-AI alignment. The detailed side-by-side is in §4.4.

*BMC Helix* is the closest architectural cousin to ServiceNow --- Helix
Discovery, Helix Operations Management, Helix AIOps, Helix ITSM. Helix
Discovery is widely regarded as the strongest agentless discovery product
on the market and is in production at multiple tier-1 banks and telcos.
AIOps capability is competent but not best-in-class; HelixGPT (the agent
layer) is newer than Now Assist. 

>*Compared to pedk.ai:* same shape of competitor as ServiceNow, with the same three differentiators applying. Helix Discovery is a natural integration source for pedk.ai's Shadow Topology layer.

### Tier 2 --- Observability Platforms with AIOps Overlays

*Splunk* dominates log-and-metrics observability in financial services.
ITSI adds service-health scoring and event correlation on top of Splunk
Enterprise; Observability Cloud adds metrics and traces; Splunk AI Assist
provides LLM-driven summarisation and search. Strengths: log volume at
scale, mature query language, deep deployment footprint in tier-1 banks.
Weaknesses: ingest-volume pricing is the well-known commercial pain at
scale; topology is service-map-driven rather than agentless-discovered.

>*Compared to pedk.ai:* strong overlap on event-correlation and incident analytics; weak overlap on discovery and on persistent memory; SaaS-only delivery (in the modern stack) is a data-sovereignty friction.

*Dynatrace* is the leading APM-led observability platform; Davis AI
provides causal-AI-driven root-cause analysis tied to a continuously
updated topology (Smartscape) derived from OneAgent instrumentation. Davis
CoPilot adds the LLM agent layer. Strongest in deep application
observability with auto-discovered service topology --- but the topology
is agent-bound, so anything without a OneAgent is invisible. 

>*Compared to pedk.ai:* Davis AI is the closest published peer in *spirit* (causal AI, topology-aware correlation). Differences are that Dynatrace's topology depends on agents (and so cannot see what is not instrumented) and that it carries no persistent memory of unresolved correlations across cycles. Pedk.ai's discovery is agentless and ingestion-driven; its memory persists up to 365 days.

*Datadog* is the broadest observability platform by data-type coverage
(metrics, logs, traces, RUM, security, network). Watchdog provides
ML-driven anomaly detection and alert grouping; Bits AI is the LLM agent
layer. Strengths: data-type breadth, modern UX, fast time-to-value.
Weaknesses: agent-based discovery, SaaS-only (sovereignty friction for FMI
India), per-host and per-event pricing that scales unpredictably.

>*Compared to pedk.ai:* strong on observability breadth, weak on discovered topology independent of agents and on persistent memory across cycles.

*New Relic, LogicMonitor, ScienceLogic SL1, AppDynamics (Cisco).* Each
occupies a slice of the observability-plus-AIOps space. *ScienceLogic
SL1* is the most notable for the pedk.ai comparison --- it offers
agentless topology discovery and CMDB reconciliation, which is the closest
single existing capability to pedk.ai's Shadow Topology. Differences: less
depth on LLM-driven hypothesis generation, no persistent abeyance memory
of unresolved correlations, no sovereign deployment posture. 

>*Compared to pedk.ai:* these are functional adjacents; none combine discovered topology, persistent semantic memory, and sovereign serving in one platform.

### Tier 3 --- Event Correlation and Noise Reduction

*BigPanda, Moogsoft (Dell), Netreo.* Sit between monitoring tools and
ITSM. Their job is to deduplicate, correlate, and suppress alerts using
statistical methods (Levenshtein fuzzy matching, K-means clustering,
temporal grouping) before they reach the ticket queue. 

>*Compared to pedk.ai:* narrow-scope competitors for the correlation function only - no discovery, no persistent memory, no hypothesis generation. Typically deployed *alongside* Tier 1 / Tier 2 platforms, not instead of them. Not head-to-head competitors with pedk.ai.


## Capability Comparison Across AIOps Platforms

| Capability                                              | \rothead{ServiceNow} | \rothead{BMC Helix} | \rothead{Dynatrace} | \rothead{Splunk ITSI} | \rothead{Datadog} | *pedk.ai*                       |
|---------------------------------------------------------|----------------------|---------------------|---------------------|-----------------------|-------------------|-----------------------------------|
| Rule-based event correlation                            | ✓                    | ✓                   | ✓                   | ✓                     | ✓                 | ✓                                 |
| ML-driven alert clustering                              | ✓                    | ✓                   | ✓ (Davis)           | ✓                     | ✓ (Watchdog)      | ✓                                 |
| Agentless discovery of IT estate                        | ✓ (ITOM)             | ✓ (Helix Discovery) | --                  | --                    | --                | ✓                                 |
| Discovered topology with confidence scores              | binary               | binary              | agent-derived       | partial               | agent-derived     | *graded confidence*             |
| Topology-aware correlation across domains               | partial (CMDB)       | partial (CMDB)      | within-APM          | partial               | partial           | ✓                                 |
| Persistent memory of unresolved breaks across cycles    | roadmap              | roadmap             | --                  | --                    | --                | *✓ (Abeyance Memory)*           |
| LLM-driven root-cause hypothesis                        | ✓ (Now Assist)       | ✓ (HelixGPT)        | ✓ (Davis CoPilot)   | ✓ (Splunk AI)         | ✓ (Bits AI)       | ✓ (TSLAM-Mini-2B, local)          |
| Falsifiable / causally tested hypotheses                | --                   | --                  | --                  | --                    | --                | *✓*                             |
| Sovereign / local-only model serving                    | --                   | --                  | --                  | --                    | --                | *✓*                             |
| Deployment model                                        | SaaS (+ gov-cloud)   | SaaS + on-prem      | SaaS                | SaaS + on-prem        | SaaS              | sovereign on-prem / OCI India     |

## Cost Comparison Across AIOps Alternatives

*Pricing in enterprise IT-operations software is heavily negotiated and
rarely public. The ranges below are indicative, derived from public
analyst commentary (Gartner, Forrester, IDC), historical RFP outcomes, and
vendor case studies. Actual pricing varies with infrastructure scale (CIs,
hosts, events ingested), number of modules, geography, and bundling. All
figures USD; 5-year TCO assumes a single FMI-scale tenant (exchange / CCP /
depository) running an integrated AIOps capability.*

| Platform | Commercial Model | \rothead{Annual Run-Rate (FMI-Scale)} | \rothead{Implementation / PS} | \rothead{5-Year Indicative TCO} | Notes |
|---|---|---|---|---|---|
| *ServiceNow* (ITSM + ITOM Discovery + Service Mapping + AIOps + Now Assist) | Subscription per fulfiller user + per CI + AIOps premium per CI/event + Now Assist premium | \$1.5M -- \$5M+ | \$0.5M -- \$2M | \$10M -- \$30M+ | AIOps add-on alone is \$200K--\$1M+/yr; pricing scales aggressively with estate size |
| *BMC Helix* (Discovery + Operations Management + AIOps + ITSM) | Subscription; more negotiable than ServiceNow | \$0.8M -- \$3M | \$0.4M -- \$1.5M | \$6M -- \$18M | Helix Discovery widely seen as best-in-class agentless discovery |
| *Splunk* (ITSI + Observability Cloud + Splunk AI Assist) | Subscription, ingest-volume based | \$1M -- \$5M+ | \$0.3M -- \$1M | \$7M -- \$28M | Volume-based pricing is the dominant cost driver; well-known commercial pain at scale |
| *Dynatrace* (Full Stack + Davis AI + Davis CoPilot) | Subscription, DPU consumption-based | \$0.6M -- \$2.5M | \$0.2M -- \$0.8M | \$4M -- \$14M | Agent-based, APM-led; Davis AI well regarded but topology is agent-bound |
| *Datadog* (Infra + Logs + APM + Watchdog + Bits AI) | Subscription, per-host + ingest-volume | \$0.4M -- \$2M | \$0.1M -- \$0.5M | \$3M -- \$12M | SaaS-only; data-sovereignty friction in India FMI |
| *New Relic* (One Platform + Applied Intelligence) | Subscription, user + ingest-volume | \$0.3M -- \$1.5M | \$0.1M -- \$0.4M | \$2M -- \$9M | Smaller FMI footprint than the four above |
| *ScienceLogic SL1* (Discovery + AIOps + ITSM integrations) | Subscription, per device | \$0.4M -- \$1.5M | \$0.2M -- \$0.7M | \$3M -- \$10M | Strongest agentless-discovery + CMDB-recon in the observability tier |
| *BigPanda / Moogsoft (Dell)* (event correlation only) | Subscription, per event/incident | \$0.3M -- \$1M | \$0.1M -- \$0.4M | \$2M -- \$6M | Narrow scope; typically deployed alongside Tier 1 / Tier 2 |
| *pedk.ai* | Sovereign-hosted subscription; local model serving (no per-call inference cost, no cloud egress) | Target band materially below incumbent integrated-suite run-rates | Light (read-only Day 1 ingestion; no production write access) | Target: < 50% of incumbent integrated-suite 5-year TCO | India-hosted, DPDPA-aligned by construction; AI-native rather than AI-bolt-on; augments rather than replaces |

**Cost drivers to note:**

- *Pricing-axis sensitivity.* ServiceNow scales on CI/user count; Splunk
  on ingest volume; Dynatrace on platform units; Datadog on host count and
  ingest. FMI estates with large telemetry volume but moderate CI count
  get hit hardest by ingest-based pricing.
- *Bundling effect.* ServiceNow and BMC Helix routinely sell across
  ITSM + ITOM + AIOps in a single deal; isolating the AIOps spend from
  the ITSM spend in vendor proposals is non-trivial and a frequent source
  of procurement confusion.
- *Implementation drag.* Tier 1 suites typically require 6--18 months
  of implementation and customisation, with services tail often matching
  the first-year license. Tier 2 observability platforms are faster (3--9
  months); Tier 3 / Tier 4 specialised tools deploy in weeks.
- *Cloud-egress + inference cost.* Every cloud-hosted AI offering
  carries per-call LLM inference cost that compounds with volume; this
  line item is absent in a local-served architecture and is the largest
  single TCO differentiator at FMI scale.

## Deep Dive: pedk.ai vs ServiceNow

ServiceNow is the most strategically relevant competitor in this
landscape: it owns the ticket layer at most FMIs, has the deepest existing
investment to defend, and has shipped (in Now Assist) the LLM-agent
capability closest in spirit to what pedk.ai is building. The technical
comparison below focuses on this incumbent specifically.

**How ServiceNow does it (technically):**

ServiceNow's AIOps operates through multiple technical layers:

*Alert Correlation (RAMC Framework)* --- prioritised sequence:

1. *Rule-Based (R)*: Custom filters, scripts, CI relationships with configurable time windows (e.g., 60-minute intervals).
2. *Automated (A)*: ML/AI patterns from historical alert data for same CI/metric combinations. Uses "aggregation algorithms that rely on historical alerts with the same alert identifier (CI and metric identifier) and which occurred multiple times in the same time frame".
3. *Manual (M)*: Operator parent-child assignment.
4. *CMDB (C)*: Groups based on CI relationships in CMDB.

*How pedk.ai compares:*

| Capability | ServiceNow | pedk.ai | Assessment |
|---|---|---|---|
| *Correlation approach* | RAMC (rule -> automated -> manual -> CMDB). Automated requires *same CI/metric* recurring in *same timeframe* | Snap Engine: 5-dimension weighted scoring (semantic, topological, temporal, operational, entity overlap) with mask-aware redistribution. Can correlate *different* descriptions of *same* problem across domains | *pedk.ai stronger for novel correlations*: ServiceNow finds patterns it has seen before. pedk.ai finds patterns nobody has seen before through semantic/topological fusion |
| *Anomaly detection* | MAD, Kalman, time-series, non-parametric -- mature, well-tested statistical stack | Surprise Engine (Mechanism 1): adaptive histogramming of snap score distributions per (tenant, failure_mode_profile), threshold starts at 99.99th percentile | *ServiceNow broader*: More statistical methods. pedk.ai's surprise engine is narrower but operates on snap scores (multi-dimensional correlation output) rather than raw metrics |
| *RCA* | 5 correlation algorithms (conditional probability, Levenshtein fuzzy matching, K-means, temporal, entity extraction) | Hypothesis Generation (TSLAM-Mini-2B falsifiable claims) + Expectation Violation (transition matrix statistical test) + Causal Direction Testing (temporal ordering consistency) | *Different paradigms*: ServiceNow uses statistical correlation. pedk.ai uses LLM-generated hypotheses validated by causal testing. pedk.ai is more ambitious but less proven |
| *Long-term memory* | LEAP mines 6 months of incident resolution notes. Knowledge Graph references CMDB. "Persistent memory" in agents but unspecified | Fragments retained 60d (telemetry) to 730d (changes) in hot/warm storage, 1095d before deletion. Cold storage with ANN search. Source-specific decay curves | *pedk.ai deeper and more structured*: ServiceNow's 6-month window is fixed and incident-only. pedk.ai retains diverse evidence types with source-specific decay and near-miss boosting |
| *Cross-domain semantic gap* | K-means text clustering + Levenshtein fuzzy matching -- limited ability to connect different vocabulary describing the same failure | 4-column embeddings: topology-aware T-VEC encoding ensures "high BLER on cell 8842-A" and "CRC errors on S1 bearer" are compared via topological neighborhood, not just text similarity | *pedk.ai significantly stronger*: This is Abeyance Memory's core innovation |
| *Ecosystem / distribution* | Massive installed base. CMDB already deployed at most Tier-1 operators. ITSM workflow integration native | Standalone platform requiring integration | *ServiceNow dominant*: Distribution advantage is overwhelming. Must integrate with, not compete against |
| *Data quality* | Security concern noted: "Knowledge Graph does leak information that should not be available for the user based on ACLs" | Tenant isolation (INV-7), dedup keys, validated schema (INV constraints) | *pedk.ai more rigorous*: Multi-tenant security is architecturally enforced |

The strategic takeaway is consistent with the broader landscape: pedk.ai
*augments* ServiceNow rather than displacing it. The integration vector
is read-only ingestion of ServiceNow incidents, changes, and CMDB on Day
1; write-back of pedk.ai-derived correlations and hypotheses into
ServiceNow tickets on Day N. Customers retain their ServiceNow investment;
pedk.ai adds the abeyance memory and discovered-topology layer ServiceNow
has not shipped.


# Engagement Plan for BSE

## What pedk.ai Does

pedk.ai is an intelligence fabric that sits between your existing systems --- monitoring platforms, ITSM tools, asset registers, change management systems --- and tells you the truth about your technology estate. It cross-correlates what your systems *actually do* (operational telemetry) against what your organisation *thinks* they do (asset register) and what your engineers *actually know* (incident and change ticket patterns).

pedk.ai *augments* your existing tools. It does not replace your monitoring platform, your ITSM system, or your asset register. They do what they're designed to do. pedk.ai adds the reconciliation layer they've never had.

pedk.ai already integrates with *ServiceNow* --- polling incidents, correlating operator actions with AI recommendations, and computing behavioural feedback to improve over time. Your existing ServiceNow investment becomes more valuable, not redundant.

## How It Works --- Day 1

pedk.ai requires no production access on Day 1. No write access to any system. No sensitive data. No market data. No trading information.

You provide three read-only historical datasets:

| What You Share | What It Contains | What pedk.ai Finds |
|----------------|------------------|-------------------|
| *Asset Register* | Your technology assets and their declared dependencies | The "documented truth" --- what you think your infrastructure looks like |
| *Monitoring History* | 3--12 months of system metrics, event logs, alert records | The "operational truth" --- what your infrastructure actually did |
| *Ticket Archive* | Incident and change ticket history | The "human truth" --- how your engineers actually fix problems |

In response, pedk.ai delivers a *Divergence Report*:

- Systems generating telemetry with no asset register record (*shadow IT* --- untracked, unpatched, unmonitored)
- Registered assets with zero operational footprint for months (*phantom systems* consuming licences and compute)
- Hardware/VM replacements detected from telemetry mismatches (*identity mutations* --- the register says Server A, but Server A was replaced by Server B six months ago)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns (*hidden single points of failure*)

*Zero risk. Zero disruption. Proven value before any deeper conversation.*