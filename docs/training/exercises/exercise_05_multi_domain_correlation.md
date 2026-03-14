# Exercise 5: Multi-Domain Correlation

**Duration:** 25 minutes
**Difficulty:** Advanced
**Learning Objectives:**
- Distinguish single root cause with cascade from simultaneous independent failures
- Use Pedk.ai's causal inference outputs to form a hypothesis
- Apply Dark Graph analysis to multi-domain incidents

## Scenario

At 09:47 WIB on a Wednesday morning, the Surabaya NOC receives simultaneous anomaly alerts across three domains:

**RAN:** 8 cells at Site SBYBDR003 showing sudden throughput collapse (avg -65% from baseline)
**Transport:** SBYHUB001–SBYHUB002 trunk link showing 94% utilisation (normal: 40%)
**Core:** Packet Core node SBYCORE001 showing session establishment rate drop (-40%)

Pedk.ai's causal inference (Transfer Entropy method) reports:
```
X→Y: SBYHUB001_utilisation → SBYBDR003_throughput (lag=2min, p=0.003)
X→Y: SBYHUB001_utilisation → SBYCORE001_session_rate (lag=4min, p=0.008)
X→Y: SBYBDR003_throughput → SBYCORE001_session_rate (p=0.31 — NOT significant)
```

Timeline reconstruction:
- 09:43 WIB: SBYHUB001–SBYHUB002 utilisation begins climbing
- 09:45 WIB: SBYBDR003 cells begin showing throughput degradation
- 09:47 WIB: SBYCORE001 session rate drop detected
- 09:49 WIB: Pedk.ai SITREP generated

External context: A large sporting event (Persebaya FC match) is scheduled at Gelora Bung Tomo Stadium, 300m from Site SBYBDR003, starting at 10:00 WIB. Pre-event crowd arriving.

## Tasks

1. Using the causal inference output, determine whether this is (a) single root cause with cascade, (b) independent simultaneous failures, or (c) an external demand spike.
2. Identify the most likely root domain and entity.
3. Recommend the immediate actions for the NOC team in priority order.

## Expected Findings

**Conclusion:** Single root cause with cascade.
**Root domain:** Transport (SBYHUB001 trunk congestion).
**Evidence:** Causal direction confirmed — SBYHUB001 Granger-causes both RAN and Core degradation with timing consistent with propagation (2min and 4min lags). RAN does not cause Core independently (p=0.31). The stadium crowd is a demand amplifier, not the root cause — it increased load on an already-congested link.

**Recommended actions (priority order):**
1. Identify cause of SBYHUB001 congestion (equipment fault vs. demand spike)
2. Activate backup transport path if available
3. Pre-position field team at SBYHUB001 hub site
4. Monitor SBYBDR003 and SBYCORE001 — if transport restored, these should recover automatically

## Scoring Criteria

| Criterion | Points | Description |
|-----------|--------|-------------|
| Correctly identifies single root cause cascade | 25 | Must cite causal inference p-values |
| Correctly identifies Transport as root domain | 20 | SBYHUB001 as root entity |
| Notes stadium event as demand amplifier, not root cause | 15 | Important nuance |
| Correct action priority order (transport first) | 25 | Treating RAN/Core as symptoms |
| References Pedk.ai causal evidence in reasoning | 15 | Cites lag times and p-values |

**Total: 100 points. Pass mark: 70 points.**

## Key Learning Points

- Causal inference direction (not just correlation) is critical for multi-domain incidents — treat the domain where causality originates as the root, not where symptoms appear loudest.
- External events (stadium, Ramadan, holidays) shift demand curves but rarely cause faults on their own — look for the infrastructure weakness they expose.
- Pedk.ai's Transfer Entropy method detects non-linear dependencies; always review lag times to confirm propagation direction before escalating.
