# Decision Memory and Abeyance

**Audience:** NOC engineers and shift leads
**Time to read:** 10 minutes

---

## What is the Decision Memory?

The Decision Memory is pedk.ai's repository of past decisions — every SITREP generated, every root cause conclusion reached, every operator override with its reason code, and every resolution outcome. It is the system's institutional knowledge.

When pedk.ai analyses a new incident, it searches the Decision Memory for similar past cases. If it finds a close match — a similar alarm cluster, similar KPI deviation, similar topology context — it draws on that precedent to inform its recommendation and set its confidence score. The more similar past cases it finds, the higher its confidence.

This is why operator feedback is so important: every override you submit with a specific reason code, and every SITREP you rate, is a contribution to the Decision Memory that makes future recommendations better.

The technical term for the Decision Memory system is **Abeyance** — from the legal concept of a matter held in suspension pending further resolution. Decisions in abeyance are held in active memory, waiting to be corroborated or contradicted by new evidence.

---

## How Fragments Decay Over Time

Not all memories are equal. Recent, well-corroborated decisions carry more weight than old, weakly-supported ones. pedk.ai implements this through a decay mechanism.

Each entry in the Decision Memory has a **decay score** that starts at 1.0 (maximum weight) when created and decays over time towards 0.0. The decay rate depends on several factors:

| Factor | Effect on decay |
|--------|----------------|
| **Time elapsed** | Score decreases gradually over days and weeks |
| **Corroboration** | Each new similar case that confirms the decision slows decay (score partially resets) |
| **Contradiction** | An override with a conflicting reason code accelerates decay |
| **Resolution outcome** | A correctly predicted and resolved incident resets decay significantly; an incorrect prediction accelerates it |
| **Operator feedback** | Positive ratings slow decay; negative ratings accelerate it |

The practical consequence: decisions that keep being confirmed stay active and influential. Decisions that were wrong — or that described a transient pattern that has not recurred — fade and eventually become dormant.

Once a fragment's decay score drops below the dormancy threshold, it moves to **cold storage**.

---

## Cold Storage Retrieval

Cold storage is the archive tier of the Decision Memory. Dormant fragments are stored in Parquet format, compressed and retained for long-term pattern recognition and regulatory audit purposes.

Cold storage is not deleted data — it is dormant data. It can be retrieved when relevant.

**When cold storage retrieval happens automatically:**

- A new incident matches the pattern signature of a cold-stored fragment with high similarity (cosine distance via pgvector similarity search)
- The retrieved fragment is promoted back to active memory and its decay score is partially reset
- pedk.ai uses the retrieved fragment to inform its analysis and notes the cold storage retrieval in the SITREP evidence chain

**When you might want to retrieve cold storage manually:**

- You are investigating a recurring fault that you believe pedk.ai should have precedent for, but the current SITREP is showing low confidence
- You want to review how a similar fault was handled in the past — useful during shift handover or incident investigation
- An engineer is investigating a pattern they recall from several months ago and wants to find the documented resolution

Cold storage retrieval is accessible via the Evidence Chain section of any SITREP — look for entries labelled "Retrieved from cold storage". The original decision timestamp and context are shown.

---

## How to Query and Review Past Decisions

Navigate to `/feedback` and select the **Decision History** tab to browse past SITREP decisions associated with your operator ID.

The search interface supports:
- **Free text** — search by entity name, site, or alarm type
- **Date range** — filter by decision date
- **Confidence band** — filter by the confidence score at the time of the decision
- **Outcome filter** — filter for decisions that were overridden, confirmed, or dismissed

For each past decision you can see:
- The original SITREP summary
- The confidence score at the time
- Whether you or another operator approved, overrode, or dismissed it
- The resolution outcome (if recorded at incident close)
- Whether the fragment is in active memory, dormant, or in cold storage

Use the **Export** button to download a CSV of your team's decision history for a date range — useful for post-incident reviews and shift handover preparation.

---

## Corroboration: Strengthening Signal with Multiple Evidence Sources

A single alarm, on its own, may mean many things. The more independent evidence sources that point to the same conclusion, the higher pedk.ai's confidence in its analysis. This is the corroboration principle.

pedk.ai draws corroborating evidence from several sources simultaneously:

1. **Decision Memory similarity** — how closely past cases match the current pattern
2. **Expert causal templates** — named failure patterns (Fibre Cut, PRB Congestion, RRU Failure) that describe known root cause chains
3. **KPI co-movement** — multiple metrics degrading together in a pattern that matches a known failure signature
4. **Topology context** — the network graph relationships that make a particular root cause plausible given what entities are affected
5. **Operator feedback history** — calibration data showing how reliable pedk.ai's analysis has been for similar patterns in the past

The confidence score calculation reflects this layering:
- Base confidence from Decision Memory alone: starts at 0.30, increases by 0.10 per matching similar case
- Expert causal evidence: adds up to 0.20 if matching causal templates are found
- Calibration adjustment: if enough historical operator feedback exists for this pattern type, the score is adjusted towards the empirical accuracy rate

The implication for your work: when you see a low-confidence SITREP, it means one or more of these corroboration sources is missing or weak. The evidence chain in the SITREP will tell you which. A case with zero matching causal templates and no similar past cases is asking you to apply your own expertise — the system genuinely does not have a reliable answer.
