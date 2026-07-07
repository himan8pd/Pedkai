---
# 1. Document Identity
title: |
  \fontsize{30}{35}\selectfont \pedkai{} - AI-native operational reconciliation engine
subtitle: "Financial Market Infrastructure Edition --- Version 2.2"
author: |
  \fontsize{20}{22}\selectfont Himanshu Thakur
date: |
  \fontsize{16}{16}\selectfont 29-Jun-2026
subject: "Product Specification - Financial Market Infrastructure"
keywords: [Dark Graph, Abeyance Memory, pedk.ai, Stock Exchange, Market Infrastructure]
lang: "en"

# 5. Layout & LaTeX Fixes + Fonts
geometry: "margin=2.5cm"
header-includes: |
  \usepackage{anyfontsize}
  \usepackage{fontspec}

  \setmainfont[
    Ligatures      = TeX,
    BoldFont       = {Inter Bold},
    ItalicFont     = {Inter Italic},
    BoldItalicFont = {Inter Bold Italic}
  ]{Inter}

  \setmonofont{Courier New}

  \newfontfamily\pedkaifont[Scale=MatchLowercase]{Space Mono}
  \definecolor{pedkcyan}{HTML}{00D4FF}
  \newcommand{\pedkai}{{\pedkaifont pedk\textcolor{pedkcyan}{.ai}}}

  \AtBeginDocument{
    \KOMAoptions{headsepline=0pt, footsepline=0pt}
    \addtokomafont{pageheadfoot}{\fontsize{9}{11}\selectfont\rmfamily\color{gray}}
  }

# 3. Header & Footer
header-left: "pedk.ai - Product Specification (Financial Market Infrastructure)"
header-right: "29-Jun-2026"
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
# \pedkai{} --- Product Overview

**AI-Native Operational Reconciliation Engine for Financial Market Infrastructure**


## The Problem Every Exchange Faces

Every stock exchange and market infrastructure operator runs on a complex technology estate --- trading engines, matching systems, market data distributors, clearing platforms, settlement systems, network infrastructure, disaster recovery sites. Dozens of vendors. Hundreds of interconnected systems. Thousands of configuration parameters.

The documented state of this infrastructure --- asset registers, configuration management databases, architecture diagrams, DR runbooks --- diverges from operational reality silently, year after year. Hardware gets replaced but the asset register isn't updated. Emergency changes during volatile trading sessions are never rolled back. Failover paths documented in the DR plan haven't been validated since the last configuration change. Systems decommissioned on paper continue to consume compute, licences, and rack space.

We call this divergence the **Dark Graph**. It exists in every exchange. And while nobody in the C-suite wakes up worrying about asset register accuracy, they worry intensely about what asset register inaccuracy causes.

The consequences are not hypothetical. In January 2023, a disaster recovery configuration error at the New York Stock Exchange broke the morning auction process, forcing the cancellation of over 4,000 trades. In October 2023, a data infrastructure performance degradation following system changes at the London Stock Exchange repeatedly halted trading for hundreds of small-cap stocks.

These are not isolated events. They are symptoms of the same structural problem: the documented state of critical infrastructure does not match what is actually running. The kind of gap \pedkai{} is built to find.


### The Bottom Line

\pedkai{} translates technical reconciliation into four hard executive value levers:

| Executive Pain Point | Business Impact | \pedkai{}'s Answer |
|----------------------|-----------------|------------------|
| **The "Integration Tax" (OPEX)** | Technology teams spend days diagnosing production issues because the system dependency maps they work from are wrong. This is dead OPEX. | By eliminating the Dark Graph, troubleshooting goes from "hunting in the dark" to "following a lit path", dropping MTTR and structural OPEX. |
| **Silent System Degradation** | Trading latency creeps upward. Market data feeds degrade. No alerts fire because thresholds aren't breached --- but trading quality erodes and participants migrate volume to competing venues. | \pedkai{} finds the degradation that traditional monitoring misses --- the slow drift that costs market share before anyone notices. |
| **Phantom Assets / Licences** | Decommissioned but fully-licenced systems (Phantom Nodes) cost real money in software renewals, hardware maintenance, and rack space. Zombie processes consume compute without generating value. | \pedkai{} identifies assets generating zero operational activity for months, enabling immediate licence clawbacks and hard savings. |
| **Systemic / Brand Risk** | Major outages occur because an undocumented dependency cascaded unexpectedly. A trading halt during market hours costs $50--200M in lost trading fees, regulatory scrutiny, and reputational damage. | Continuous reconciliation makes system brittleness visible before the critical collapse occurs. |


## What \pedkai{} Does

\pedkai{} is an intelligence fabric that sits between your existing systems --- monitoring platforms, ITSM tools, asset registers, change management systems --- and tells you the truth about your technology estate. It cross-correlates what your systems actually do (operational telemetry) against what your organisation thinks they do (asset register) and what your engineers actually know (incident and change ticket patterns).

\pedkai{} augments your existing tools. It does not replace your monitoring platform, your ITSM system, or your asset register. They do what they're designed to do. \pedkai{} adds the reconciliation layer they've never had.

\pedkai{} already integrates with ServiceNow --- polling incidents, correlating operator actions with AI recommendations, and computing behavioural feedback to improve over time. Your existing ServiceNow investment becomes more valuable, not redundant.


## How It Works --- Day 1

\pedkai{} requires no production access on Day 1. No write access to any system. No sensitive data. No market data. No trading information.

You provide three read-only historical datasets:

| What You Share | What It Contains | What \pedkai{} Finds |
|----------------|------------------|-------------------|
| **Asset Register** | Your technology assets and their declared dependencies | The "documented truth" --- what you think your infrastructure looks like |
| **Monitoring History** | 3--12 months of system metrics, event logs, alert records | The "operational truth" --- what your infrastructure actually did |
| **Ticket Archive** | Incident and change ticket history | The "human truth" --- how your engineers actually fix problems |

Within a few weeks, \pedkai{} delivers a **Divergence Report**:

- Systems generating telemetry with no asset register record (**shadow IT** --- untracked, unpatched, unmonitored)
- Registered assets with zero operational footprint for months (**phantom systems** consuming licences and compute)
- Hardware/VM replacements detected from telemetry mismatches (**identity mutations** --- the register says Server A, but Server A was replaced by Server B six months ago)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns (**hidden single points of failure**)

Zero risk. Zero disruption. Proven value before any deeper conversation.


## Core Capabilities

### Dark Graph Reconciliation

\pedkai{}'s foundational capability. Discovers the six types of divergence between operational reality and documented intent:

- **Shadow systems** --- infrastructure that operates but isn't in the asset register (dev systems in production, unauthorised data feeds, forgotten test instances)
- **Phantom assets** --- registered systems that no longer exist or function (decommissioned servers still drawing licences, stale DR entries)
- **Undocumented dependencies** --- real operational links between systems that no architecture diagram records
- **Phantom dependencies** --- documented failover paths and data flows that carry no traffic (your DR plan says System A fails over to System B --- but System B hasn't received a heartbeat in 9 months)
- **Attribute drift** --- parameters that have been changed in production but never updated in the register (a firmware upgrade changed the default config, nobody noticed)
- **Identity mutations** --- hardware or VM replacements where the function persists but the physical identity has changed (the hostname is the same, the MAC address is different)


### Abeyance Memory

\pedkai{}'s unique differentiator. Traditional monitoring processes events in real-time and discards what it can't resolve. \pedkai{} does not discard. It remembers.

Unresolved technical fragments --- a stack trace pasted into a ticket note, a transient latency spike that didn't repeat, a reference to an unknown IP address in a change record --- are held in persistent semantic storage using four complementary embeddings per fragment --- semantic, topological, temporal, and operational (up to 1536 dimensions each) generated by a local, on-premises embedding model. No cloud API, no per-call cost, no data leaving your perimeter. Days, weeks, or months later, when a new piece of evidence arrives that matches, \pedkai{} connects the dots across time and across data types.

The system is implemented with a 5-dimension correlation engine (semantic similarity, topological proximity, temporal alignment, operational fingerprint, entity overlap) that can connect different descriptions of the same problem across technology domains --- something no text-matching system can achieve. Fragments follow a managed lifecycle with source-specific retention (alerts 90 days, change records up to 2 years), relevance decay, and cold storage archival.

Consider: a network engineer notes an unusual routing path in a change ticket. Three months later, a storage administrator reports intermittent latency on a database cluster. Six months after that, a trading system shows order execution delays during peak volume. Abeyance Memory connects these fragments --- the routing change created a suboptimal path that only becomes visible under load, affecting the database, which affects trading latency. No human analyst could spot this across three teams, three systems, and nine months of tickets.

No competing product ships this today. ServiceNow's correlation requires the same CI/metric recurring in the same timeframe, and its LEAP capability mines only resolved incident notes over a fixed window. Splunk processes events and moves on. Dynatrace maps dependencies in real-time but doesn't hold unresolved fragments. Industry analysts flag persistent cross-incident memory as the next capability frontier.


### Silent Degradation Detection

The most dangerous failures are the ones that don't trigger alerts. A trading system reports "healthy" to monitoring but order execution latency has crept from 2ms to 14ms over six weeks. A market data feed passes all health checks but is delivering stale prices 0.3% of the time. No thresholds are breached. No alarms fire. But trading quality erodes, participants notice, and volume migrates to competing venues --- silently, irreversibly.

\pedkai{} detects this class of invisible degradation through multiple complementary methods:

- **Baseline deviation analysis** --- flagging systems whose current performance metrics diverge from their own historical baselines, even when absolute values remain within threshold
- **Peer comparison** --- identifying systems performing significantly worse than peers of the same type, configuration, and workload profile
- **Correlation decoupling** --- detecting when metrics that should move together suddenly diverge (e.g., order volume rises but execution throughput flatlines, or market data input rates increase but distribution latency remains flat)
- **Multi-dimensional pattern recognition** --- identifying complex degradation signatures that span multiple metrics and would evade any single-threshold alert
- **Configuration-to-performance correlation** --- using causal inference to detect when a specific configuration change caused a performance shift that went unnoticed


### Change Impact Intelligence

Every exchange tracks changes. \pedkai{} does something different: it connects configuration changes to operational consequences.

By correlating change ticket timestamps with system performance metrics using causal inference (PCMCI, Granger causality, Transfer Entropy), \pedkai{} identifies:

- Changes that caused performance degradation nobody noticed
- Emergency changes during market hours that were never rolled back
- Configuration parameters reset by software upgrades that were never re-applied
- Cumulative "drift" --- multiple small changes that individually look harmless but collectively degrade system behaviour

The pattern is always the same: a change is made under pressure, a rollback is forgotten, a default is silently reset by an upgrade. Individually, each is invisible. Collectively, they create the conditions for a systemic failure during peak load --- exactly when the cost is highest.


### Disaster Recovery Readiness Verification

DR plans are documents. \pedkai{} verifies whether they match reality.

By comparing your production asset register against your DR asset register, and cross-referencing both against operational telemetry, \pedkai{} identifies:

- Failover paths that exist on paper but show zero operational evidence (phantom dependencies)
- DR systems that have drifted out of sync with production since the last validation
- Configuration changes applied to production but not replicated to DR
- Systems added to production after the last DR plan update
- DR-site hardware that has aged past its production equivalents --- surfaced as identity mutations and register inaccuracies long before a failover ever depends on it
- Security-agent, antivirus, and patch-level drift between production and DR --- DR nodes silently running behind or ahead of the production baseline (attribute drift)
- Update and security policies whose enforcement actions --- agent updates, signature refreshes, forced reboots --- could fire inside a protected trading window, detected by correlating change and maintenance-window activity against market-hours timelines

This is not a DR test. It is a continuous, passive verification that your DR plan reflects the current state of production --- without any disruption to either environment.

Regulatory DR drills are scheduled, observed, and unforgiving. The value of \pedkai{} is that it makes this divergence visible continuously and in advance of the rehearsal --- so the exercise validates recovery, rather than discovering that aged DR hardware, an out-of-date security agent, or a policy-driven update was waiting to disrupt the demonstration at exactly the wrong moment.


### Technology Operations Intelligence

\pedkai{} provides Technology Operations teams with AI-generated situational reports that explain anomalies in plain language, identify root causes through graph-based analysis, and recommend actions. Support for multi-system anomaly detection across trading, market data, clearing, settlement, and network infrastructure, with escalation path recommendations based on severity and business impact.


## Operator Control --- Always

\pedkai{}'s autonomy is a spectrum. You choose your comfort level:

| Level | What \pedkai{} Does | What You Do |
|:-----:|------------------|-------------|
| **Advisory** | Generates reports and recommendations. Takes zero action. | Full manual control. |
| **Assisted** | Creates draft tickets with pre-populated fields. | You review and dispatch every ticket. |
| **Supervised** | Executes routine actions with an override window. | You can veto any action before it takes effect. |
| **Gated** | Executes approved action types with safety gates. | You review the audit trail. Kill-switch available. |

Default: Advisory. You advance only when you're ready.

\pedkai{} learns from what your operators actually do --- not just button clicks, but real operational actions. When \pedkai{} recommends an action and your operator takes a different one, that delta is the learning signal that makes \pedkai{} smarter over time.


## Trust Progression

| Timeline | What Happens | Your Risk |
|----------|-------------|-----------|
| **Day 1** | Offline analysis of historical data. Divergence Report delivered. | None. Read-only. No production access. |
| **Month 3** | Shadow mode alongside existing monitoring. Accuracy validated. | None. Read-only production feeds. |
| **Month 6** | Advisory mode. Situational reports generated for Technology Operations. | None. Advisory only. No automated actions. |
| **Month 12+** | Deeper integration discussed only after proven value. | Earned trust. You decide the pace. |


## Regulatory Alignment

\pedkai{}'s capabilities align directly with regulatory requirements for financial market infrastructure operators:

- **SEBI Cybersecurity and Cyber Resilience Framework (CSCRF)**: SEBI Circular SEBI/HO/ITD/ITD-SEC-1/P/CIR/2024/113, dated 20 August 2024, mandates comprehensive asset inventory management, change management controls, and cyber resilience measures for all SEBI Regulated Entities. Phase 1 compliance deadline was 1 January 2025; Phase 2 was 1 April 2025. The framework requires exchanges and Market Infrastructure Institutions (MIIs) to maintain accurate, auditable technology asset registers. \pedkai{}'s Dark Graph reconciliation provides continuous, automated verification of the asset accuracy that CSCRF mandates.

- **SEBI Algorithmic Trading Framework**: SEBI Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, dated 4 February 2025, establishes mandatory audit trails, kill switches, and pre-trade risk management for algorithmic trading. Each algo order must carry a unique identifier for traceability. The framework requires brokers to maintain detailed logs for all API activity for a minimum of 5 years. \pedkai{}'s change impact intelligence and Abeyance Memory provide the long-horizon correlation across these audit trails that point-in-time audits cannot.

- **CPMI-IOSCO Principles for Financial Market Infrastructures (PFMI)**: BIS CPMI Publication No. 101, April 2012 (updated). Principle 17 (Operational Risk) requires FMIs to "identify the plausible sources of operational risk, both internal and external, and mitigate their impact through the use of appropriate systems, policies, procedures, and controls." Key Consideration 6 requires business continuity plans that enable critical IT systems to resume operations within two hours following disruptive events. \pedkai{} identifies the undocumented dependencies and configuration drift that are the largest sources of unquantified operational risk, and continuously validates that DR infrastructure matches production state.

- **ISO/IEC 27001:2022**: Annex A Control A.5.9 (Inventory of information and other associated assets) requires organisations to maintain an accurate, current inventory of information assets. Control A.8.9 (Configuration management) requires documented configurations to be established and maintained. \pedkai{} automates the continuous validation of both requirements by detecting divergence between documented and actual asset states.

- **SEBI Technology Advisory Committee**: Mandates periodic technology risk assessments and disaster recovery testing for MIIs. Following the NSE trading halt of 24 February 2021, SEBI intensified scrutiny of exchange technology infrastructure design and capacity validation. \pedkai{} automates the evidence generation for technology audits that are currently manual and error-prone.

- **Security and Data Sovereignty**: JWT authentication, hierarchical RBAC, tenant data isolation, data sovereignty controls. \pedkai{} processes operational metadata only --- no market data, no trading data, no participant information. Runs entirely on-premises. Your data never leaves your infrastructure. No cloud dependency. No third-party data processing.


## Cost Advantage

\pedkai{}'s architecture delivers enterprise-grade operational intelligence at a fraction of incumbent pricing:

| Capability | Incumbent Cost | \pedkai{} |
|------------|---------------|---------|
| **AI inference** | Cloud LLM APIs: $0.01--$0.06 per 1K tokens, scaling with volume | Locally-served small language model (CPU) + local embeddings: zero marginal cost per call |
| **Licensing** | ServiceNow ITSM + ITOM: $250--$360/agent/month. 100 agents = $300K--$430K/year | No per-agent model. Annual subscription based on estate size |
| **Deployment** | 6--18 month implementation. Consulting fees 1--3x annual licence | Docker single-command deployment. Operational in days, not months |
| **Data sovereignty** | Cloud-only (ServiceNow SaaS, Google Vertex AI, Splunk Cloud). Data leaves your premises | Runs entirely on-premises. Your data never leaves your infrastructure |

For financial market infrastructure operators who cannot justify ServiceNow's total cost of ownership (3--5x the licence fee), or who cannot send operational data to cloud services due to regulatory constraints, \pedkai{} delivers comparable operational intelligence at 10--20% of the cost --- entirely within your perimeter.


## Deployment

\pedkai{} deploys on Kubernetes with Docker containers. On-premises only for financial market infrastructure (cloud-hosted SaaS available for other verticals). Supports PostgreSQL with TimescaleDB for time-series analytics, Apache Kafka for telemetry streaming, and vector search for semantic intelligence.

Validated on ARM and x86 infrastructure with Docker Compose for single-command deployment. Kubernetes manifests available for production scaling.

No heavyweight infrastructure requirements. No rip-and-replace migration. \pedkai{} operates alongside your existing monitoring stack from Day 1.


## Quality Process

\pedkai{} has been subjected to a rigorous multi-phase review cycle:

- **Three-pass technical audit**: forensic code review, architecture viability assessment, and adversarial red-team review
- **Five-member executive committee**: spanning operations, strategy, engineering, QA, and executive leadership
- **Formal remediation cycle**: structured gap analysis with tracked resolution
- **Erdos AI methodology**: independent assessment using the Erdos Enterprise AI Deployment Framework, covering product readiness, business case integration, and workforce readiness

This is not a prototype presented as a product. It is an engineered system that has been systematically challenged, found wanting in specific areas, and improved through structured remediation.


## Evidence-Based Approach

\pedkai{} uses pluggable mathematical frameworks for evidence fusion --- selecting the optimal approach based on your data landscape. Organisations with rich monitoring telemetry benefit from one methodology; those with sparse, policy-gated environments benefit from another.

Causal inference uses established statistical methods for time-series analysis (PCMCI, Granger causality, Transfer Entropy), with a roadmap to incorporate more advanced techniques for non-linear and multi-variable causality as they mature.

The approach is configurable per deployment. No one-size-fits-all.


## How \pedkai{} Compares

| Capability | ServiceNow | Splunk | Dynatrace | \pedkai{} |
|------------|-----------|--------|-----------|---------|
| **Cross-system correlation** | Same CI/metric must recur in same timeframe | Log correlation within search window | Real-time dependency mapping | 5-dimension semantic fusion across different vocabulary and systems |
| **Unresolved evidence** | Discards after processing | Retained in index, not correlated | Real-time only | Holds indefinitely in Abeyance Memory |
| **Asset enrichment** | Active discovery (ping-based, blind behind firewalls) | No asset model | Auto-discovered topology | Passive discovery from telemetry + tickets + asset register cross-correlation |
| **Model serving** | Cloud SaaS only | Cloud SaaS or on-prem | Cloud SaaS | On-premises only: zero cloud dependency for sensitive environments |
| **Cost** | $300K--$8M/year (licence + implementation) | $1M+ for enterprise (ingest-based) | $500K+ (host-based) | Enterprise licence based on estate size |
| **Deployment time** | 6--18 months | 3--6 months | 2--4 weeks (agent-based) | Days to weeks (Docker, no agents) |

\pedkai{} does not compete with these platforms. It augments them --- adding the reconciliation layer that makes existing investments work harder. Your Splunk deployment becomes more valuable when \pedkai{} tells it which assets to watch. Your ServiceNow CMDB becomes more accurate when \pedkai{} identifies the drift.


## The Conversation \pedkai{} Enables

\pedkai{} doesn't ask you to trust it. It asks you to test it.

Share historical data --- asset register, monitoring exports, change tickets. Get a Divergence Report. If it finds value, continue the conversation. If it doesn't, you've lost nothing.

The question isn't whether your asset register has gaps. It does. Every asset register does. The question is whether you want to find them before they find you --- during market hours, with the regulator watching.


## Current Capabilities and Roadmap

| Shipped today | In active development |
|---------------|-----------------------|
| Dark Graph divergence reporting with per-finding provenance and data-completeness scoring | Cross-domain long-horizon correlation |
| Fragment lifecycle with append-only audit trail | Operator-feedback weight calibration |
| Local model serving | Cold-storage recall |
| ServiceNow read-only integration | Adaptive discovery mechanisms --- flagged experimental |
| 7-gate action safety framework | |
