# Feedback and Operator Learning

**Audience:** NOC engineers and shift leads
**Time to read:** 8 minutes

---

## Why Operator Feedback Matters

pedk.ai's confidence scores and SITREP quality do not stay constant over time. They improve — or degrade — based on how operators engage with the system's outputs.

When you rate a SITREP, submit an override with a reason code, or dismiss a false positive, you are providing ground truth data: what actually happened, whether the AI was right, and where it went wrong. This data feeds back into the confidence calibration system, updating the historical performance profile for similar future patterns.

The cycle works like this:

```
pedk.ai generates a SITREP
  → You review it critically
    → You rate it or override it with a specific reason
      → The rating updates the confidence calibration for that pattern type
        → Future SITREPs of the same type are more accurately scored
          → Your team can trust the confidence numbers more
```

An NOC team that consistently provides structured feedback will see measurably better SITREP quality within weeks. A team that dismisses or accepts without rating will see no improvement — the system has no signal to learn from.

---

## How to Submit Structured Feedback

Feedback is submitted from the incident detail view. Every incident has a **Feedback** panel at the bottom.

**Structured rating — 4 dimensions:**

| Dimension | What you are rating | Why it matters |
|-----------|--------------------|--------------------|
| **Accuracy** (1–5) | Was the root cause identification correct? | Core training signal — tells the system whether its topology reasoning was right |
| **Relevance** (1–5) | Was the SITREP focused on the right entities and domain? | Tells the system whether its clustering and scoping was appropriate |
| **Actionability** (1–5) | Were the recommended steps useful and executable? | Tells the system whether its remediation suggestions reflect real NOC procedures |
| **Timeliness** (1–5) | Did the SITREP arrive soon enough to be useful? | Flags latency in the detection and analysis pipeline |

**Rating scale:**

| Score | Meaning |
|-------|---------|
| 5 | Correct / excellent |
| 4 | Mostly correct, minor gap |
| 3 | Partially useful — notable errors or omissions |
| 2 | Mostly wrong but something was useful |
| 1 | Entirely incorrect or unhelpful |

**Free-text note** — optional but valuable. The most useful notes are specific:
- "Root cause wrong — fault was the feeder at RRU, not the baseband unit" (useful)
- "Confidence too high — this pattern has a hardware explanation that the AI is missing" (useful)
- "Not great" (not useful)

**Override feedback** — if you override a recommendation rather than accepting it, you are prompted for a reason code. Select the most specific applicable code and add a free-text explanation. An override with a specific reason code is the highest-quality learning signal in the system — it tells pedk.ai not only that something was wrong but precisely what was wrong and what the correct analysis was.

---

## The ServiceNow Integration

pedk.ai integrates with ServiceNow (and compatible ITSM platforms) to create a feedback loop from ITSM actions back to the AI system.

**What flows from ServiceNow to pedk.ai:**

- **Resolution codes** — how a ticket was closed. If the resolution matches pedk.ai's recommended action, this is a positive learning signal. If it diverges, this is an implicit override signal.
- **Change ticket outcomes** — if a change ticket was raised as a result of a pedk.ai recommendation and the change resolved the fault, this confirms the causal chain.
- **Incident duration** — the time from pedk.ai's first alert to ticket resolution is a measure of MTTR improvement, tracked in the value scorecard.

**What flows from pedk.ai to ServiceNow:**

- At Level 1 (Assisted), pedk.ai generates draft tickets pre-populated with root cause, affected entities, severity, and recommended action fields drawn from the SITREP
- At Level 2+ (Supervised), approved actions can create, update, or close tickets automatically within the approved scope

The ServiceNow integration is configured by your platform Engineering team. If you notice that pedk.ai-generated ticket fields are incorrectly populated — wrong entity names, wrong severity codes, or missing fields — this is a mapping issue to report to Engineering, not a data problem to correct manually in ServiceNow.

---

## Viewing Your Feedback History

Navigate to `/feedback` to access your feedback history.

The **My Feedback** tab shows all ratings you have submitted, ordered by date. For each entry you can see:
- The incident ID and SITREP summary
- Your ratings across the four dimensions
- The free-text note you added (if any)
- Whether the feedback has been incorporated into the calibration model (status shown as "Processed")

The **Team Metrics** tab (visible to shift leads and NOC managers) shows:
- Team-level feedback completion rate — what percentage of SITREPs have been rated
- Average ratings by dimension over the past 30 days
- Override rate — percentage of SITREPs that received an operator override
- Feedback quality breakdown — proportion of overrides with specific reason codes vs. generic dismissals

Target metrics for a well-functioning team:
- Feedback completion: >70% of SITREPs rated
- Override rate: 10–30% (below 10% may indicate rubber-stamping; above 30% may indicate calibration issues)
- Specific override reason rate: >80% of overrides with a specific reason code, not just a generic rejection

---

## How Feedback Improves Future Recommendations

The improvement mechanism works at two levels:

**Calibration bins** — pedk.ai groups similar decisions into bins based on their evidence profile (Decision Memory hits, causal template matches). Once a bin accumulates 50 or more operator feedback ratings, the system switches from its heuristic confidence formula to the empirical average from your feedback. Your team's actual experience of the system's accuracy in that pattern category directly sets the confidence score for future similar cases.

**Decision Memory updates** — overrides with reason codes update the Decision Memory directly. If you override a SITREP that attributed a fault to a baseband unit and record that the actual cause was a transport link, this creates a new memory fragment with the correct causal chain. Future incidents matching the same alarm profile will find this corrected fragment during similarity search and inherit its attribution.

**Causal template refinement** — when a pattern of overrides points consistently to a gap in pedk.ai's expert knowledge (for example, a new failure mode introduced by a vendor software release), Engineering uses the override data to create or update a causal template. This is not automatic — it requires Engineering to review the pattern — but the data that enables it comes directly from structured overrides in the NOC.

The practical timeline: calibration improvements are visible within days to weeks for common fault patterns. Template-based improvements, which require Engineering input, take longer but have broader effect across all similar cases.
