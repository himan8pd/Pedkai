# ADR-002: Autonomous Execution Architecture

**Status:** Planning (Gates future autonomous work)  
**Version:** 1.0  
**Date:** February 25, 2026  
**Authors:** Product, Architecture, Compliance Teams  
**Sign-Off Required:** CTO, Chief Legal Officer, CFO  

---

## 1. Context & Problem Statement

**Pedkai's current state:** Advisory-only platform generating recommendations for human engineer execution.

**The ask:** Can Pedkai execute preventive actions autonomously (without human approval) to maximize response time and operational efficiency?

**The constraint:** Network infrastructure is critical — unintended changes could cause enterprise-scale outages affecting millions of customers and revenue.

**Decision required:** Which autonomy model to pursue, and at what investment level?

---

## 2. Options Reconsidered

### Option A: Advisory-Only (Current State)

**Scope:** No change. Pedkai identifies issues → generates SITREPs → engineers execute.

**Pros:**
- Zero risk of unintended network-wide failures
- No complex policy engine required
- Fast initial time-to-market (Pedkai already at this state)
- Aligns with "safe AI" principles

**Cons:**
- Human-in-the-loop remains a bottleneck (typical response 15–45 min)
- Competitive disadvantage if autonomous competitors emerge
- Misaligns with "Self-Healing Network" aspirations
- Does not unlock full ROI potential (30–40% improvement capped)

**Effort:** 0 months (current state)  
**Cost:** £0  
**Market Positioning:** Decisioning platform, not autonomous system

---

### Option B: Advisory with Opt-in Auto-Execution (Recommended for Phase 5)

**Scope:** Pedkai can autonomously execute **specific, low-risk actions** for **tenants that opt-in**, subject to safety gates.

**Allowed Action Categories (candidate list for Phase 5):**
1. **Cell Failover within sector** (traffic steering between adjacent sites)
   - Risk: Medium (momentary subscriber impact if misconfigured)
   - Rollback: Immediate (reverse traffic steering in <5 seconds)
2. **Connection Pool Throttling** (reduce new connections to saturated NE)
   - Risk: Low (only prevents new connections, doesn't terminate active ones)
   - Rollback: Immediate (resume connections)
3. **Alarm Silencing** (mute false-positive alarms from known junky sensors)
   - Risk: Very Low (only suppresses notifications)
   - Rollback: Immediate (re-enable alarms)
4. **TTL/QoS Parameter Tuning** (shift traffic engineering parameters by <10%)
   - Risk: Medium (could redistribute load unpredictably)
   - Rollback: Requires vendor confirmation

**NOT allowed (too risky for Phase 5):**
- Configuration changes to core routers or switching fabric
- Spectrum allocation changes
- BSS billing parameter changes
- Any change affecting SLA tiers or T&Cs

**Safety Gates for Opted-in Tenants:**

| Gate | Owner | Trigger | Timeout |
| --- | --- | --- | --- |
| **Pre-execution Policy Check** | Policy Engine | Confirm action complies with tenant policy | 2 sec |
| **Blast-Radius Estimation** | Digital Twin (mock in Phase 5) | Predict KPI impact on connected entities | 5 sec |
| **Confidence Threshold** | Decision Memory | Similarity score ≥ 0.75 to past successful actions | — |
| **Confirmation Window** | Human (async) | Window for human override before execution | 30 sec (configurable) |
| **Kill-Switch** | Human (manual) | Emergency stop endpoint available 24/7 | — |

**Pros:**
- Progressive autonomy — risk managed per-action and per-tenant
- Quick wins (cell failover alone could improve MTTR by 20–30%)
- Aligns with Phase 5 roadmap (Decision Memory + RL already built)
- Compliance-friendly (explicit audit trail + kill-switch)

**Cons:**
- Significant implementation effort (Phase 5, 8–12 weeks)
- Requires robust Policy Engine (currently basic)
- Digital Twin must be at least functional (not production-grade)
- Insurance implications (liability shift from human to platform)

**Effort:** 10–15 weeks (Phase 5 expansion)  
**Cost:** £280k–£450k (policy engine hardening + DT mock + testing)  
**Market Positioning:** "Guided autonomous telco platform"

**Phase 5 Roadmap (if chosen):**
- **Week 1–2:** Policy Engine v2 (versioning, audit trail, explicit gates)
- **Week 3–4:** Digital Twin (mock — predict failover impact via historical data)
- **Week 5–7:** Safety Rails (confirmation windows, kill-switch, blast-radius limits)
- **Week 8–10:** Implementation (cell failover as first action type)
- **Week 11–12:** Validation (staging network, >1000 test scenarios)

---

### Option C: Fully Autonomous (Future Strategic Play)

**Scope:** All recommendations executed by default unless explicitly blocked by policy or human override.

**Target Timeline:** Phase 7+ (12+ months out)

**Pros:**
- Maximum efficiency (response time <2 minutes for most incidents)
- Purest realization of "AI Native OS" vision
- Market differentiation if competitors are slower

**Cons:**
- Extremely high risk of catastrophic failure without mature safety systems
- Regulatory approval likely impossible in UK/EU for critical infrastructure
- Insurance industry not ready (no precedent for autonomous network changes)
- Requires complete internal culture shift and liability model change
- Failed autonomy could result in regulatory intervention or license loss

**Effort:** Unknown (requires Phase 5 as foundation + Phase 6 hardening)  
**Cost:** £1M+ (safety certification, compliance work, insurance)  
**Market Positioning:** Enterprise risk — not recommended for Phase 5

---

## 3. Recommended Path Forward

**Chosen Option: B (Advisory with Opt-in Auto-Execution)**

**Rationale:**
1. Balances innovation with risk management
2. Aligns with current engineering roadmap
3. Allows staged rollout (start with safest action type)
4. Maintains board/regulator confidence
5. Positions for future scaling if Phase 5 succeeds

**Gate for Proceeding:**
- Board approval of Phase 5 business case (ROI, risk profile)
- CTO sign-off on safety architecture
- Legal/Compliance review of insurance implications
- CFO approval of Phase 5 budget (£300k–£400k)

---

## 4. Architecture: Option B Implementation

### 4.1 Safety Rails

```
┌─────────────────────────────────────────────────────────────────────┐
│                   AUTONOMOUS ACTION PIPELINE                         │
├─────────────────────────────────────────────────────────────────────┤
│ 1. DETECTION PHASE (Pedkai Core)                                    │
│    - Anomaly detected                                                │
│    - SITREPs generated                                               │
│                                                                     │
│ 2. POLICY GATE                                                       │
│    - ✓ Policy permits action for this tenant?                       │
│    - ✓ Blast-radius < configured limit?                             │
│    - If NO → STOP and escalate to human                             │
│                                                                     │
│ 3. CONFIDENCE GATE                                                   │
│    - ✓ Decision Memory similarity ≥ 0.75?                           │
│    - ✓ Past success rate for this action ≥ 90%?                    │
│    - If NO → STOP and recommend to human                            │
│                                                                     │
│ 4. CONFIRMATION WINDOW (30 sec default)                             │
│    - Human receives ASYNC notification (not blocking)               │
│    - Human has 30 sec to:                                           │
│      • [Override] Stop execution                                    │
│      • [Approve Early] Execute immediately                          │
│      • [Ignore] Let timer expire → Execute                          │
│                                                                     │
│ 5. EXECUTION                                                         │
│    - Query Netconf session to target NE                             │
│    - Apply change within <2 sec                                     │
│    - Log action to audit trail with trace_id                        │
│                                                                     │
│ 6. VALIDATION                                                        │
│    - Poll KPIs for 5 min post-execution                             │
│    - If degradation detected → ROLLBACK (see below)                 │
│    - Record outcome to Decision Memory (RL feedback loop)           │
│                                                                     │
│ 7. KILL-SWITCH (Available 24/7)                                     │
│    - Human calls POST /api/v1/autonomous/kill-switch               │
│    - Reverts last N actions in FIFO order                           │
│    - Suitable for "something went wrong" scenarios                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Rollback & Remediation

**Automatic Rollback Triggers:**
1. Post-execution KPI analysis (5-min window) shows degradation > 10%
2. SLA violation detected in affected zone
3. 5+ new high-severity alarms within 2 min of execution
4. Network topology change detected (unexpected failover)

**Rollback Procedure:**
```
ACTION_EXECUTED
    ↓
[Wait 5 min for KPI collection]
    ↓
KPIs Degraded? → YES → QUERY Digital Twin for rollback impact
                          → EXECUTE rollback (reverse change)
                          → LOG "AUTO_ROLLBACK" to audit trail
                          → ALERT operations team
                ↓ NO
Impact acceptable? → YES → CLOSE incident (success)
               ↓ NO
Mark as "HUMAN_REVIEW_REQUIRED" → Escalate
```

### 4.3 Netconf/YANG Adapter

**Current State:** Not implemented  
**Effort Estimate:** 6–8 weeks (vendor-specific per device type)

**Required for:**
- Cell Site Router (Ericsson RBS, Nokia AirScale)
- Packet Core (3GPP N06 interface)
- Optical Transport (LEMO abstraction)

**Vendor-by-Vendor Breakdown:**

| Vendor | Equipment | YANG Model | Effort | Risk |
| --- | --- | --- | --- | --- |
| **Ericsson** | RBS 6/7 Series | Proprietary + OpenDaylight | 4 weeks | Medium |
| **Nokia** | AirScale, SSR | NETCONF standard | 3 weeks | Low |
| **Cisco** | ASR/ISR | IOS-XE (NETCONF/RESTCONF) | 2 weeks | Low |
| **Juniper** | MX Series | Contrail, standard YANG | 2 weeks | Low |
| **Others** | Huawei, ZTE, Mavenir | Varies widely | 6+ weeks | High |

**Build vs. Buy Decision:**
- **Build:** 16–20 weeks total (all vendors) — internally maintained, locked to specific vendor versions
- **Buy:** Potential $200–$500k licensing (e.g., Nokia Paragon Automation) — vendor-maintained, frequent updates, broader compatibility, but less customization

**Recommendation:** Negotiate vendor support contracts; start with Nokia + Cisco Proof-of-Concept (6 weeks), then expand.

---

## 5. Digital Twin Feasibility (Phase 5 Context)

### 5.1 What's a Digital Twin for This Context?

A model that predicts network KPI changes in response to a configuration change *before* executing it.

**Simple Version (Phase 5 OK):**
- Use historical data: "When we did failover X before, KPIs changed by Δ"
- Deterministic rules: "If PRB > 70%, failover to adjacent costs 2% throughput"
- Output: Risk score (0–100) and predicted KPI impact

**Sophisticated Version (Phase 6+):**
- Real queuing theory models (Jackson networks, M/M/c queues)
- Traffic engineering models (segment routing, path constraints)
- Vendor performance models (Ericsson RBS throughput curves)

### 5.2 Buy vs. Build

**Buy Options:**
- **Juniper Paragon Planner:** £300–500k/year, full vendor integration, mature, but rigid
- **VIAVI NITRO:** £400–600k/year, good lab-to-live transfer, but niche
- **Nokia ACP:** Bundled with automation contracts, good for Nokia-heavy networks
- Custom build (via consulting): £150–250k, bespoke to telco, 12–16 weeks

**Build Option (Recommended for Phase 5):**
- Use Decision Memory search: "Find past decisions where similar drift occurred"
- Apply simple heuristic: impact = similarity_score × historical_impact_magnitude
- Result: "80% confident this action will improve MTTR by 25 ± 8%"
- Cost: £40–60k + 2 weeks engineering (integrate with Gemini embeddings)

**Recommendation:** Build Phase 5 mock DT using Decision Memory; re-evaluate buy in Phase 6 based on Phase 5 outcomes.

---

## 6. Risk Assessment

### 6.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
| --- | --- | --- | --- |
| Unintended cascade failover (multiple sites) | Medium | Critical | Blast-radius gate + per-tenant action limits |
| False confidence (similarity search fails) | Medium | High | Require N≥50 historical decisions + manual calibration |
| Network topology changes unexpectedly | Low | Critical | Policy gate checks current topology before execution |
| Rollback fails (NE unreachable) | Low | High | Netconf session heartbeat + timeout override |

### 6.2 Operational Risks

| Risk | Probability | Impact | Mitigation |
| --- | --- | --- | --- |
| Operations team unprepared | Medium | Medium | Mandatory Phase 5 training + simulator |
| Kill-switch abused (human overrides valid actions) | Medium | Low | Audit trail + feedback loop |
| SLA breach due to autonomous action | Low | Critical | 7-day shadow mode before auto-enable |

### 6.3 Regulatory & Insurance Risks

**Regulatory (OFCOM, ICO):**
- **Current State:** No specific guidance on autonomous network changes in UK
- **Risk:** OFCOM could mandate human approval (reducing autonomy benefit from 30% to 5%)
- **Mitigation:** Engage pre-Phase 5 with regulatory affairs; publish safety whitepaper
- **Timeline:** Expect 4–6 month review cycle

**Insurance:**
- **Current State:** General E&O insurance covers advisory system behavior
- **Risk:** Autonomous actions may be excluded or require rider
- **Mitigation:** Obtain cyber liability + E&O rider covering "autonomous operational changes" (est. +20% premium)
- **Cost:** +£50–100k/year additional insurance

---

## 7. Governance & Stakeholder Sign-Offs

### 7.1 Pre-Phase 5 Approvals Required

| Stakeholder | Approval | Timeline |
| --- | --- | --- |
| **CTO** | Architecture, safety design, Phase 5 roadmap | 2 weeks |
| **Chief Legal** | Regulatory review, insurance implications | 4 weeks |
| **CISO** | Security of Netconf sessions, auth, audit | 2 weeks |
| **CFO** | Phase 5 budget (£300–400k), insurance rider cost | 1 week |
| **Board** | Business case, autonomy positioning statement | 3 weeks |

### 7.2 During Phase 5

| Governance Gate | When | Owner | Criteria |
| --- | --- | --- | --- |
| **Policy Engine v2 Review** | Week 3 | CTO | All rules versioned, audit logged |
| **Digital Twin Validation** | Week 5 | Architecture | N=100 test cases, accuracy ≥ 85% |
| **Staging Lock-In** | Week 10 | Ops | >1000 simulated executions, 0 critical issues |
| **Shadow Mode Approval** | Week 11 | Ops + Risk | 7-day production shadow, 0 incidents |
| **Auto-Enable Approval** | Week 13 | Board | All gates passed, proceed to auto-enabled tenants |

---

## 8. Regulatory Clearance Checklist

**UK-Specific Regulatory Path:**

### OFCOM (Telecommunications Regulator)

- [ ] Pre-notification meeting (current Q: Feb 2026)
- [ ] Formal safety whitepaper submission (Q2 2026)
- [ ] Demonstration of rollback mechanisms (Q2 2026)
- [ ] Customer opt-in consent review (Q3 2026)
- [ ] 90-day implementation notice (if required) (Q3 2026)

**Likely Outcome:** Conditional approval with mandatory:
- Annual third-party security audit
- Kill-switch availability certification
- Customer notification policy

### ICO (Information Commissioner)

- [ ] PIA (Privacy Impact Assessment) for telemetry collection
- [ ] DPIA (Data Protection Impact Assessment) for decision tracing
- [ ] Consent mechanism review (if storing operator feedback)
- [ ] Data retention policy (audit logs, decision traces)

**Likely Outcome:** Standard consent + retention policy (no blockers)

---

## 9. Effort & Cost Summary

### Phase 5 Full Implementation Cost

| Component | Effort | Cost | Notes |
| --- | --- | --- | --- |
| Policy Engine v2 Hardening | 3 weeks | £60k | Versioning, audit, rule validation |
| Digital Twin Mock (Decision Memory–based) | 2 weeks | £40k | Integrate search with heuristic impact |
| Safety Rails (gates, kill-switch, rollback) | 4 weeks | £80k | Async notification, state machine testing |
| Netconf/YANG (Nokia + Cisco PoC) | 6 weeks | £120k | Vendor engagement + adapter implementation |
| Testing & Validation (staging) | 3 weeks | £60k | >1000 scenarios, chaos engineering |
| Regulatory Engagement | Ongoing | £30k | Legal, compliance consultants |
| **Total** | **18 weeks** | **£390k** | — |

### Ongoing (Post-Phase 5)

| Item | Cost/Year | Notes |
| --- | --- | --- |
| Insurance rider (cyber + E&O) | £50–100k | Autonomous-specific coverage |
| Regulatory compliance updates | £20k | Annual filing / demonstrations |
| Vendor contract support (Netconf) | £50–100k | Nokia, Cisco, Ericsson |
| **Annual OpEx** | **£120–220k** | — |

---

## 10. Decision & Sign-Offs

### Chosen Direction

**Pedkai shall pursue Option B (Advisory with Opt-in Auto-Execution) with Phase 5 implementation roadmap as specified in this ADR.**

### Prerequisites to Phase 5 Kickoff

- [ ] CTO signs off on architecture and safety design
- [ ] CFO approves £390k Phase 5 budget and £120–220k annual ongoing costs
- [ ] Chief Legal confirms regulatory path and insurance rider feasibility
- [ ] Board approves autonomy positioning statement
- [ ] OFCOM pre-notification meeting scheduled

### Governance Going Forward

- This ADR supersedes ADR-001 and locks the autonomy strategy for 18 months
- Quarterly Board updates on Phase 5 progress and regulatory engagement
- Monthly CTO reviews of safety rails and test coverage
- Post-Phase 5 (Month 16) formal "Autonomous Execution Go/No-Go" decision

---

## Sign-Off Section

| Role | Name | Signature | Date | Notes |
| --- | --- | --- | --- | --- |
| **CTO** | [PENDING] | [PENDING] | [PENDING] | Architecture & safety |
| **Chief Legal** | [PENDING] | [PENDING] | [PENDING] | Regulatory & liability |
| **Chief Financial Officer** | [PENDING] | [PENDING] | [PENDING] | Budget & insurance |
| **Board Chair** | [PENDING] | [PENDING] | [PENDING] | Strategic approval |

---

## Appendices

### A. Key References
- **ADR-001:** Autonomy Positioning Decision (Phase 0)
- **Value Methodology:** [docs/value_methodology.md](docs/value_methodology.md)
- **Phase 5 Roadmap:** (Separate document, TBD)
- **Safety Rails Specification:** (Separate detailed design doc, TBD)

### B. Glossary

- **Blast-radius:** The set of entities affected by a single configuration change
- **Confirmation Window:** Grace period before execution during which humans can override
- **Decision Memory:** Pedkai's historical decision trace store (DecisionTraceORM)
- **Kill-switch:** Emergency stop endpoint to revert recent autonomous actions
- **Netconf/YANG:** Industry-standard network automation protocols
- **Policy Engine:** Rule engine enforcing tenant-specific constraints on actions
- **Rollback:** Automated reversal of a change if KPIs degrade post-execution

---

**Document Owner:** Architecture Team  
**Last Updated:** February 25, 2026  
**Next Review:** Upon Phase 5 kickoff approval (expected Q2 2026)
