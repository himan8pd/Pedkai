---
# 1. Document Identity
title: |
  \fontsize{30}{35}\selectfont pedk.ai - AI-native operational reconciliation engine
subtitle: "Financial Market Infrastructure Edition --- Version 1.0"
author: |
  \fontsize{20}{22}\selectfont Himanshu Thakur
date: |
  \fontsize{16}{16}\selectfont 13-Apr-2026
subject: "Product Specification - Financial Market Infrastructure"
keywords: [Dark Graph, Abeyance Memory, pedk.ai, Stock Exchange, Market Infrastructure]
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
header-left: "pedk.ai - Product Specification (Financial Market Infrastructure)"
header-right: "13-Apr-2026"
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
# pedk.ai --- Product Overview

**AI-Native Operational Reconciliation Engine for Financial Market Infrastructure**


## The Problem Every Exchange Faces

Every stock exchange and market infrastructure operator runs on a complex technology estate --- trading engines, matching systems, market data distributors, clearing platforms, settlement systems, network infrastructure, disaster recovery sites. Dozens of vendors. Hundreds of interconnected systems. Thousands of configuration parameters.

The documented state of this infrastructure --- asset registers, configuration management databases, architecture diagrams, DR runbooks --- diverges from operational reality silently, year after year. Hardware gets replaced but the asset register isn't updated. Emergency changes during volatile trading sessions are never rolled back. Failover paths documented in the DR plan haven't been validated since the last configuration change. Systems decommissioned on paper continue to consume compute, licences, and rack space.

We call this divergence the **Dark Graph**. It exists in every exchange. And while nobody in the C-suite wakes up worrying about asset register accuracy, they worry intensely about what asset register inaccuracy *causes*.

The consequences are not hypothetical. On 24 February 2021, trading at the National Stock Exchange of India halted for nearly four hours after a telecom link failure cascaded into the clearing system. SEBI's investigation revealed faulty design and insufficient capacity in critical trading infrastructure --- problems that existed in the documented architecture but had never been validated against operational reality. NSE and NSE Clearing paid Rs 72.64 crore to settle the matter. In October 2023, BSE experienced connectivity failures that forced brokers including ICICI Direct and Sharekhan to redirect clients to NSE mid-session. In July 2025, SEBI barred Jane Street Group from Indian markets and froze approximately Rs 4,843 crore ($566M) in assets over algorithmic trading manipulation --- a case that exposed gaps in how automated trading systems are audited and monitored in production.

These are not isolated events. They are symptoms of the same structural problem: the documented state of critical infrastructure does not match what is actually running. The kind of gap pedk.ai is built to find.


### The Bottom Line

pedk.ai translates technical reconciliation into four hard executive value levers:

| Executive Pain Point | Business Impact | pedk.ai's Answer |
|----------------------|-----------------|------------------|
| **The "Integration Tax" (OPEX)** | Technology teams spend days diagnosing production issues because the system dependency maps they work from are wrong. This is dead OPEX. | By eliminating the Dark Graph, troubleshooting goes from "hunting in the dark" to "following a lit path", dropping MTTR and structural OPEX. |
| **Silent System Degradation** | Trading latency creeps upward. Market data feeds degrade. No alerts fire because thresholds aren't breached --- but trading quality erodes and participants migrate volume to competing venues. | pedk.ai finds the degradation that traditional monitoring misses --- the slow drift that costs market share before anyone notices. |
| **Phantom Assets / Licences** | Decommissioned but fully-licenced systems (Phantom Nodes) cost real money in software renewals, hardware maintenance, and rack space. Zombie processes consume compute without generating value. | pedk.ai identifies assets generating zero operational activity for months, enabling immediate licence clawbacks and hard savings. |
| **Systemic / Brand Risk** | Major outages occur because an undocumented dependency cascaded unexpectedly. A trading halt during market hours costs $50--200M in lost trading fees, regulatory scrutiny, and reputational damage. | Continuous reconciliation makes system brittleness visible *before* the critical collapse occurs. |


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

Within a few weeks, pedk.ai delivers a **Divergence Report**:

- Systems generating telemetry with no asset register record (**shadow IT** --- untracked, unpatched, unmonitored)
- Registered assets with zero operational footprint for months (**phantom systems** consuming licences and compute)
- Hardware/VM replacements detected from telemetry mismatches (**identity mutations** --- the register says Server A, but Server A was replaced by Server B six months ago)
- Undocumented operational dependencies discovered from engineer troubleshooting patterns (**hidden single points of failure**)

**Zero risk. Zero disruption. Proven value before any deeper conversation.**


## Core Capabilities

### Dark Graph Reconciliation

pedk.ai's foundational capability. Discovers the six types of divergence between operational reality and documented intent:

- **Shadow systems** --- infrastructure that operates but isn't in the asset register (dev systems in production, unauthorised data feeds, forgotten test instances)
- **Phantom assets** --- registered systems that no longer exist or function (decommissioned servers still drawing licences, stale DR entries)
- **Undocumented dependencies** --- real operational links between systems that no architecture diagram records
- **Phantom dependencies** --- documented failover paths and data flows that carry no traffic (your DR plan says System A fails over to System B --- but System B hasn't received a heartbeat in 9 months)
- **Attribute drift** --- parameters that have been changed in production but never updated in the register (a firmware upgrade changed the default config, nobody noticed)
- **Identity mutations** --- hardware or VM replacements where the function persists but the physical identity has changed (the hostname is the same, the MAC address is different)


### Abeyance Memory

pedk.ai's unique differentiator. Traditional monitoring processes events in real-time and discards what it can't resolve. pedk.ai does not discard. It remembers.

Unresolved technical fragments --- a stack trace pasted into a ticket note, a transient latency spike that didn't repeat, a reference to an unknown IP address in a change record --- are held in persistent semantic storage using domain-tuned 1536-dimensional embeddings built on FinGPT, an open-source financial LLM framework that understands financial infrastructure terminology natively. Days, weeks, or months later, when a new piece of evidence arrives that matches, pedk.ai **connects the dots** across time and across data types.

The system is implemented with a **5-dimension correlation engine** (semantic similarity, topological proximity, temporal alignment, operational fingerprint, entity overlap) that can connect different descriptions of the same problem across technology domains --- something no text-matching system can achieve. Fragments follow a managed lifecycle with source-specific retention (alerts 90 days, change records up to 2 years), relevance decay, and cold storage archival.

Consider: a network engineer notes an unusual routing path in a change ticket. Three months later, a storage administrator reports intermittent latency on a database cluster. Six months after that, a trading system shows order execution delays during peak volume. Abeyance Memory connects these fragments --- the routing change created a suboptimal path that only becomes visible under load, affecting the database, which affects trading latency. No human analyst could spot this across three teams, three systems, and nine months of tickets.

No competing product does this. ServiceNow's correlation requires the same CI/metric recurring in the same timeframe. Splunk processes events and moves on. Dynatrace maps dependencies in real-time but doesn't hold unresolved fragments. Abeyance Memory is patient. It finds connections that no human analyst could spot across thousands of tickets and millions of events.


### Silent Degradation Detection

The most dangerous failures are the ones that don't trigger alerts. A trading system reports "healthy" to monitoring but order execution latency has crept from 2ms to 14ms over six weeks. A market data feed passes all health checks but is delivering stale prices 0.3% of the time. No thresholds are breached. No alarms fire. But trading quality erodes, participants notice, and volume migrates to competing venues --- silently, irreversibly.

pedk.ai detects this class of invisible degradation through multiple complementary methods:

- **Baseline deviation analysis** --- flagging systems whose current performance metrics diverge from their own historical baselines, even when absolute values remain within threshold
- **Peer comparison** --- identifying systems performing significantly worse than peers of the same type, configuration, and workload profile
- **Correlation decoupling** --- detecting when metrics that should move together suddenly diverge (e.g., order volume rises but execution throughput flatlines, or market data input rates increase but distribution latency remains flat)
- **Multi-dimensional pattern recognition** --- identifying complex degradation signatures that span multiple metrics and would evade any single-threshold alert
- **Configuration-to-performance correlation** --- using causal inference to detect when a specific configuration change caused a performance shift that went unnoticed


### Change Impact Intelligence

Every exchange tracks changes. pedk.ai does something different: it connects **configuration changes** to **operational consequences**.

By correlating change ticket timestamps with system performance metrics using causal inference (PCMCI, Granger causality, Transfer Entropy), pedk.ai identifies:

- Changes that caused performance degradation nobody noticed
- Emergency changes during market hours that were never rolled back
- Configuration parameters reset by software upgrades that were never re-applied
- Cumulative "drift" --- multiple small changes that individually look harmless but collectively degrade system behaviour

The pattern is always the same: a change is made under pressure, a rollback is forgotten, a default is silently reset by an upgrade. Individually, each is invisible. Collectively, they create the conditions for a systemic failure during peak load --- exactly when the cost is highest.


### Disaster Recovery Readiness Verification

DR plans are documents. pedk.ai verifies whether they match reality.

By comparing your production asset register against your DR asset register, and cross-referencing both against operational telemetry, pedk.ai identifies:

- Failover paths that exist on paper but show zero operational evidence (phantom dependencies)
- DR systems that have drifted out of sync with production since the last validation
- Configuration changes applied to production but not replicated to DR
- Systems added to production after the last DR plan update

This is not a DR test. It is a continuous, passive verification that your DR plan reflects the current state of production --- without any disruption to either environment.


### Technology Operations Intelligence

pedk.ai provides Technology Operations teams with AI-generated situational reports that explain anomalies in plain language, identify root causes through graph-based analysis, and recommend actions. Support for multi-system anomaly detection across trading, market data, clearing, settlement, and network infrastructure, with escalation path recommendations based on severity and business impact.


## Operator Control --- Always

pedk.ai's autonomy is a spectrum. You choose your comfort level:

| Level | What pedk.ai Does | What You Do |
|:-----:|------------------|-------------|
| **Advisory** | Generates reports and recommendations. Takes zero action. | Full manual control. |
| **Assisted** | Creates draft tickets with pre-populated fields. | You review and dispatch every ticket. |
| **Supervised** | Executes routine actions with an override window. | You can veto any action before it takes effect. |
| **Gated** | Executes approved action types with safety gates. | You review the audit trail. Kill-switch available. |

**Default: Advisory.** You advance only when you're ready.

pedk.ai learns from what your operators actually do --- not just button clicks, but real operational actions. When pedk.ai recommends an action and your operator takes a different one, that delta is the learning signal that makes pedk.ai smarter over time.


## Trust Progression

| Timeline | What Happens | Your Risk |
|----------|-------------|-----------|
| **Day 1** | Offline analysis of historical data. Divergence Report delivered. | None. Read-only. No production access. |
| **Month 3** | Shadow mode alongside existing monitoring. Accuracy validated. | None. Read-only production feeds. |
| **Month 6** | Advisory mode. Situational reports generated for Technology Operations. | None. Advisory only. No automated actions. |
| **Month 12+** | Deeper integration discussed only after proven value. | Earned trust. You decide the pace. |


## Regulatory Alignment

pedk.ai's capabilities align directly with regulatory requirements for financial market infrastructure operators:

- **SEBI Cybersecurity and Cyber Resilience Framework (CSCRF)**: SEBI Circular SEBI/HO/ITD/ITD-SEC-1/P/CIR/2024/113, dated 20 August 2024, mandates comprehensive asset inventory management, change management controls, and cyber resilience measures for all SEBI Regulated Entities. Phase 1 compliance deadline was 1 January 2025; Phase 2 was 1 April 2025. The framework requires exchanges and Market Infrastructure Institutions (MIIs) to maintain accurate, auditable technology asset registers. pedk.ai's Dark Graph reconciliation provides continuous, automated verification of the asset accuracy that CSCRF mandates.

- **SEBI Algorithmic Trading Framework**: SEBI Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, dated 4 February 2025, establishes mandatory audit trails, kill switches, and pre-trade risk management for algorithmic trading. Each algo order must carry a unique identifier for traceability. The framework requires brokers to maintain detailed logs for all API activity for a minimum of 5 years. pedk.ai's change impact intelligence and Abeyance Memory provide the long-horizon correlation across these audit trails that point-in-time audits cannot.

- **CPMI-IOSCO Principles for Financial Market Infrastructures (PFMI)**: BIS CPMI Publication No. 101, April 2012 (updated). Principle 17 (Operational Risk) requires FMIs to "identify the plausible sources of operational risk, both internal and external, and mitigate their impact through the use of appropriate systems, policies, procedures, and controls." Key Consideration 6 requires business continuity plans that enable critical IT systems to resume operations within two hours following disruptive events. pedk.ai identifies the undocumented dependencies and configuration drift that are the largest sources of unquantified operational risk, and continuously validates that DR infrastructure matches production state.

- **ISO/IEC 27001:2022**: Annex A Control A.5.9 (Inventory of information and other associated assets) requires organisations to maintain an accurate, current inventory of information assets. Control A.8.9 (Configuration management) requires documented configurations to be established and maintained. pedk.ai automates the continuous validation of both requirements by detecting divergence between documented and actual asset states.

- **SEBI Technology Advisory Committee**: Mandates periodic technology risk assessments and disaster recovery testing for MIIs. Following the NSE trading halt of 24 February 2021, SEBI intensified scrutiny of exchange technology infrastructure design and capacity validation. pedk.ai automates the evidence generation for technology audits that are currently manual and error-prone.

- **Security and Data Sovereignty**: JWT authentication, hierarchical RBAC, tenant data isolation, data sovereignty controls. pedk.ai processes operational metadata only --- no market data, no trading data, no participant information. Runs entirely on-premises. Your data never leaves your infrastructure. No cloud dependency. No third-party data processing.


## Cost Advantage

pedk.ai's architecture delivers enterprise-grade operational intelligence at a fraction of incumbent pricing:

| Capability | Incumbent Cost | pedk.ai |
|------------|---------------|---------|
| **AI inference** | Cloud LLM APIs: $0.01--$0.06 per 1K tokens, scaling with volume | Local FinGPT-based LLM (CPU) + local embeddings: **zero marginal cost per call** |
| **Licensing** | ServiceNow ITSM + ITOM: $250--$360/agent/month. 100 agents = $300K--$430K/year | No per-agent model. Annual subscription based on estate size |
| **Deployment** | 6--18 month implementation. Consulting fees 1--3x annual licence | Docker single-command deployment. Operational in days, not months |
| **Data sovereignty** | Cloud-only (ServiceNow SaaS, Google Vertex AI, Splunk Cloud). Data leaves your premises | Runs entirely on-premises. Your data never leaves your infrastructure |

For financial market infrastructure operators who cannot justify ServiceNow's total cost of ownership (3--5x the licence fee), or who cannot send operational data to cloud services due to regulatory constraints, pedk.ai delivers comparable operational intelligence at 10--20% of the cost --- entirely within your perimeter.


## Deployment

pedk.ai deploys on Kubernetes with Docker containers. On-premises only for financial market infrastructure (cloud-hosted SaaS available for other verticals). Supports PostgreSQL with TimescaleDB for time-series analytics, Apache Kafka for telemetry streaming, and vector search for semantic intelligence.

Validated on ARM and x86 infrastructure with Docker Compose for single-command deployment. Kubernetes manifests available for production scaling.

No heavyweight infrastructure requirements. No rip-and-replace migration. pedk.ai operates alongside your existing monitoring stack from Day 1.


## Quality Process

pedk.ai has been subjected to a rigorous multi-phase review cycle:

- **Three-pass technical audit**: forensic code review, architecture viability assessment, and adversarial red-team review
- **Five-member executive committee**: spanning operations, strategy, engineering, QA, and executive leadership
- **Formal remediation cycle**: structured gap analysis with tracked resolution
- **Erdos AI methodology**: independent assessment using the Erdos Enterprise AI Deployment Framework, covering product readiness, business case integration, and workforce readiness

This is not a prototype presented as a product. It is an engineered system that has been systematically challenged, found wanting in specific areas, and improved through structured remediation.


## Evidence-Based Approach

pedk.ai uses pluggable mathematical frameworks for evidence fusion --- selecting the optimal approach based on your data landscape. Organisations with rich monitoring telemetry benefit from one methodology; those with sparse, policy-gated environments benefit from another.

Causal inference uses established statistical methods for time-series analysis (PCMCI, Granger causality, Transfer Entropy), with a roadmap to incorporate more advanced techniques for non-linear and multi-variable causality as they mature.

The approach is configurable per deployment. No one-size-fits-all.


## How pedk.ai Compares

| Capability | ServiceNow | Splunk | Dynatrace | pedk.ai |
|------------|-----------|--------|-----------|---------|
| **Cross-system correlation** | Same CI/metric must recur in same timeframe | Log correlation within search window | Real-time dependency mapping | 5-dimension semantic fusion across different vocabulary and systems |
| **Unresolved evidence** | Discards after processing | Retained in index, not correlated | Real-time only | **Holds indefinitely** in Abeyance Memory |
| **Asset enrichment** | Active discovery (ping-based, blind behind firewalls) | No asset model | Auto-discovered topology | Passive discovery from telemetry + tickets + asset register cross-correlation |
| **Model serving** | Cloud SaaS only | Cloud SaaS or on-prem | Cloud SaaS | **On-premises only**: zero cloud dependency for sensitive environments |
| **Cost** | $300K--$8M/year (licence + implementation) | $1M+ for enterprise (ingest-based) | $500K+ (host-based) | Enterprise licence based on estate size |
| **Deployment time** | 6--18 months | 3--6 months | 2--4 weeks (agent-based) | Days to weeks (Docker, no agents) |

pedk.ai does not compete with these platforms. It **augments** them --- adding the reconciliation layer that makes existing investments work harder. Your Splunk deployment becomes more valuable when pedk.ai tells it which assets to watch. Your ServiceNow CMDB becomes more accurate when pedk.ai identifies the drift.


## The Conversation pedk.ai Enables

pedk.ai doesn't ask you to trust it. It asks you to **test it**.

Share historical data --- asset register, monitoring exports, change tickets. Get a Divergence Report. If it finds value, continue the conversation. If it doesn't, you've lost nothing.

The question isn't whether your asset register has gaps. It does. Every asset register does. The question is whether you want to find them before they find you --- during market hours, with the regulator watching.
