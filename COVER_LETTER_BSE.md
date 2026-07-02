---
title: |
  \fontsize{26}{30}\selectfont pedk.ai
subtitle: "Cover Letter --- Financial Market Infrastructure"
date: |
  \fontsize{14}{14}\selectfont 29-Jun-2026
lang: "en"

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

header-left: "pedk.ai"
header-right: "29-Jun-2026"
footer-left: "Confidential"
footer-right: "Page \\thepage"

titlepage: false
---

29 June 2026

**Dr Mangesh Tayde**  
Bombay Stock Exchange  
Mumbai, India

Dear Dr Tayde,

**Re: pedk.ai --- AI-native operational reconciliation for market infrastructure**

Thank you for the opportunity to discuss the operational technology challenges facing the Exchange. I appreciated the candour of our conversation, and I have given careful thought to the specific pressures your teams carry --- particularly around assurance that the documented state of critical infrastructure genuinely matches what is running in production, and that recovery capability is verifiably ready when it is called upon.

I founded pedk.ai to solve exactly this problem. Every exchange runs on a sprawling technology estate where the documented truth --- asset registers, configuration databases, DR runbooks --- diverges silently from operational reality, year after year. We call that gap the **Dark Graph**, and pedk.ai is built to find it. It sits alongside your existing monitoring, ITSM, and asset-management investments --- augmenting them, never replacing them --- and continuously reconciles what your systems *actually do* against what your organisation *believes* they do.

For an institution in your position, three capabilities matter most:

- **Disaster Recovery readiness verification** --- continuous, passive confirmation that your DR estate truly mirrors production: aged hardware, security-agent and patch-level drift, and update policies whose enforcement could disrupt a regulator-observed drill are surfaced *in advance*, not discovered mid-exercise.
- **Abeyance Memory** --- a patient correlation engine that retains unresolved technical fragments across months and connects them when later evidence arrives, exposing the slow-building, cross-team failure conditions no point-in-time tool can see.
- **Silent degradation and change-impact intelligence** --- detecting the latency creep, configuration drift, and un-rolled-back emergency changes that erode trading quality long before any threshold alarm fires.

pedk.ai runs entirely within your perimeter. It processes operational metadata only --- no market data, no trading data, no participant information --- and requires no production or write access on Day 1. Its capabilities map directly to the SEBI CSCRF asset-inventory and change-management mandates, CPMI-IOSCO PFMI operational-risk principles, and ISO/IEC 27001 configuration-management controls.

I have enclosed our full product specification, **pedk.ai --- Product Specification (Financial Market Infrastructure), Version 2.2, dated 29 June 2026**, as a PDF accompanying this letter. It sets out the architecture, capabilities, deployment model, and a zero-risk evaluation path that proves value against your own historical data before any deeper commitment.

I would welcome the chance to walk you and your team through it at your convenience, and to discuss how a no-obligation Divergence Report could be produced from read-only historical data alone.

With warm regards,

\vspace{6pt}

**Himanshu Thakur**  
Founder, pedk.ai  
himan8pd@yahoo.com
