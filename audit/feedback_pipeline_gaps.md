# Operator Feedback Pipeline Audit Report
**Date:** 2026-03-10
**Scope:** Pedkai backend feedback loop infrastructure
**Status:** Complete analysis of 6 maturity dimensions

---

## 1. DecisionFeedbackORM Schema

**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/models/decision_trace_orm.py` (lines 82-99)

**Table Name:** `decision_feedback`

**Schema (PostgreSQL):**
```
Column Name        Type                              Constraints
─────────────────  ──────────────────────────────────  ──────────────────
id                 UUID                              PRIMARY KEY, default=gen_random_uuid()
decision_id        UUID                              NOT NULL, indexed
operator_id        String(255)                       NOT NULL, indexed
score              Integer                           NOT NULL (1-5 star, or 1/-1 in practice)
comment            Text                              NULLABLE (added via migration 006)
created_at         DateTime(timezone=True)           NOT NULL, server_default=now()

Unique Constraint: (decision_id, operator_id) - One vote per operator per decision
```

**Key Design Decisions:**
- Junction table enables multi-operator feedback without overwriting
- UUID primary key for audit trail
- Comment field optional, supports qualitative feedback
- Created_at immutable (server-side timestamp) prevents tampering
- Composite unique index prevents duplicate votes from same operator

---

## 2. Feedback API Endpoints

### Endpoint 1: POST /operator/feedback
**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/api/operator_feedback.py` (lines 20-96)
**Router Registration:** `/Users/himanshu/Projects/Pedkai/backend/app/main.py` line 287-288

**Request Schema:**
```python
class OperatorFeedbackRequest(BaseModel):
    decision_id: str              # UUID of decision
    operator_id: str              # Operator identifier
    score: int                    # 1 or -1 only (binary feedback)
    action: str | None = None     # 'dismiss' | 'confirm' | None
    notes: str | None = None      # Optional commentary
```

**Response Schema:**
```json
{
  "ok": true,
  "decision_id": "uuid-string",
  "aggregate_score": 5,           # SUM of all feedback scores for this decision
  "idempotent": false             # Optional: true if this was update, false if new
}
```

**HTTP Status:**
- 200: Success
- 400: Invalid score (must be 1 or -1)
- 500: Database failure during recording or aggregation

**Behavioral Logic:**
1. **Idempotency Check:** Query for existing feedback (same operator, same decision)
   - If exists and score unchanged: return immediately with `idempotent=true`
   - If exists and score changed: update score, recalculate aggregate
2. **Record Creation:** Insert new feedback row with server-side timestamp
3. **Aggregate Update:** SUM all feedback scores for the decision, cache in `decision_traces.feedback_score`
4. **Action Handling:** If `action == 'dismiss'`, mark decision trace as `status='dismissed'`
5. **Commit:** All changes transactional (rollback on error)

**Known Limitation:** Hardcoded to 1 or -1 binary scores; schema supports 1-5 but not used

---

### Endpoint 2: POST /{decision_id}/upvote
**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/api/decisions.py` (lines 336-357)
**Method:** POST
**Status Code:** 200

**Request:** No body required

**Response Schema:**
```json
{
  "status": "upvoted",
  "decision_id": "uuid-string"
}
```

**Internal Behavior:**
- Records feedback with hardcoded `operator_id="operator_1"` and `score=1`
- Calls `DecisionTraceRepository.record_feedback()`

---

### Endpoint 3: POST /{decision_id}/downvote
**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/api/decisions.py` (lines 360-381)
**Method:** POST
**Status Code:** 200

**Request:** No body required

**Response Schema:**
```json
{
  "status": "downvoted",
  "decision_id": "uuid-string"
}
```

**Internal Behavior:**
- Records feedback with hardcoded `operator_id="operator_1"` and `score=-1`
- Calls `DecisionTraceRepository.record_feedback()`

---

## 3. ITSM Integration

**Search Result:** NOT FOUND

No evidence of ServiceNow, JIRA, Remedy, or any ITSM system integration in:
- `/backend/app` (all modules)
- `/backend/alembic` (migration history)
- Configuration files

**Grep Results:**
```bash
grep -r "itsm\|servicenow\|ServiceNow\|ITSM\|jira\|remedy" \
  /Users/himanshu/Projects/Pedkai/backend --include="*.py"
# Returns: (empty)
```

**Status:** ITSM integration is NOT implemented. Feedback remains internal to Pedkai.

---

## 4. RL Evaluator Service

**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/rl_evaluator.py` (lines 1-193)

**Service Class:** `RLEvaluatorService`

**Wiring Status:** ACTIVE and integrated

**Integration Points:**
1. **Decisions API:** `/Users/himanshu/Projects/Pedkai/backend/app/api/decisions.py` line 318
   - Triggered when outcome is recorded via POST `/{decision_id}/outcome`
   - Evaluates decision impact and applies automated feedback

2. **Incidents API:** `/Users/himanshu/Projects/Pedkai/backend/app/api/incidents.py` line 462
   - Triggered during incident close
   - Applies reward/penalty based on incident resolution success

**Evaluation Logic:**
```
Total Reward = KPI Improvement Reward + Policy Adherence Bonus/Penalty

1. KPI Improvement Reward (lines 53-147):
   - Query pre-decision baseline (30m window before)
   - Query post-decision performance (30m window after)
   - Calculate improvement delta %
   - If delta > reward_threshold (default 0.10): +5 to +15 points (scaled)
   - If delta < penalty_threshold (default -0.05): -10 points
   - Else: 0 points (neutral)

2. Policy Adherence Check (lines 38-49):
   - Evaluate decision against Telco Constitution (Policy Engine)
   - If violation: -5 points penalty
   - If compliant + success: +2 points bonus

Reward Constants:
  REWARD_SUCCESS = 5
  PENALTY_FAILURE = -10
  PENALTY_POLICY_VIOLATION = -5
  BONUS_CONSTITUTIONAL = 2
```

**Metric Mapping Strategy:**
- **Preferred:** Explicit `decision.context.external_context['target_metric']`
- **Fallback:** Heuristic mapping based on trigger description
  - "latency|ping|delay" → "latency"
  - "drop|disconnect|failure" → "call_drop_rate"
  - "congestion|prb|traffic|overloaded" → "prb_utilization"
  - default: "throughput"

**System Operator ID:** `"pedkai:rl_evaluator"` (recorded in decision_feedback table)

**Factory Function:** `get_rl_evaluator(db_session=None)` (line 191)

---

## 5. Decision Tracking & Memory Integration

**File Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/decision_repository.py` (lines 208-261)

**Feedback Boost in Similarity Search (lines 195-206):**
```python
# Finding #5: Adjusted similarity = raw + (0.1 * feedback_score)
feedback_boost = 0.1 * orm_obj.feedback_score
adjusted_sim = sim + feedback_boost
```

**Impact:** High-feedback decisions appear higher in semantic search results, creating reinforcement loop for good decisions.

**Aggregate Feedback in Repository (lines 245-261):**
- `record_feedback()` method updates `decision_traces.feedback_score` with SUM of all operator votes
- Used in similarity re-ranking (lines 177-206)
- Cache prevents N+1 queries on each search

**Calibration Statistics (lines 263-290):**
- `get_calibration_stats()` queries historical feedback for binned confidence
- Supports drift calibration by confidence tier

**Reasoning Chain & Descendants (lines 319-380):**
- `get_reasoning_chain()`: Traces parent-child decision hierarchy up to root
- `get_descendants()`: Lists all follow-up decisions triggered by a given decision
- Both use recursive CTEs to prevent N+1 issues
- Enables feedback propagation through decision lineage (not yet implemented)

---

## 6. Maturity Dimension Status

### Dimension 1: Thumbs Up/Down (Binary Feedback)
**Status:** ✅ IMPLEMENTED

**Evidence:**
- `/operator/feedback` endpoint accepts score 1 or -1
- `/upvote` and `/downvote` endpoints provide UI shortcuts
- DecisionFeedbackORM stores as Integer (allows future expansion to 1-5)

**Gaps:**
- No UI component for feedback submission (backend only)
- No feedback visualization or aggregation dashboard
- Binary forced to ±1; 5-star capability unused

---

### Dimension 2: Multi-Operator Aggregation
**Status:** ✅ IMPLEMENTED

**Evidence:**
- Composite unique index `(decision_id, operator_id)` prevents duplicate votes
- `decision_traces.feedback_score` caches SUM of all feedback
- Each operator can vote once; updates allowed (idempotent)
- RL system votes as separate operator `"pedkai:rl_evaluator"`

**Gaps:**
- No operator identity resolution (UUID or role-based)
- No historical audit of who voted when/why
- No voting context (e.g., which network state, which KPI threshold)
- No weighted voting (all operators treated equally)

---

### Dimension 3: Behavioral Observation
**Status:** ⚠️ PARTIAL (Implicit)

**Evidence:**
- Feedback comment field available (P3.5 migration)
- RL Evaluator observes actual KPI outcomes (30m pre/post windows)
- Memory hits and causal evidence tracked in decision_traces
- Decision outcome recorded with status/metrics

**Gaps:**
- No structured observation schema (free-text comments only)
- No operator observation metadata (e.g., time feedback given, network conditions)
- RL evaluator only observes KPI delta, not end-to-end business impact
- No failure mode tracking (why a decision failed)

---

### Dimension 4: Structured Assessment
**Status:** ❌ NOT IMPLEMENTED

**Evidence:**
- No rubric/checklist table
- No structured scoring criteria
- No assessment template system
- Risk assessment field exists in decision_trace schema but unused

**Gaps:**
- No formal assessment framework
- No competency evaluation
- No decision quality rubric
- No assessment audit trail

---

### Dimension 5: ITSM Ingestion
**Status:** ❌ NOT IMPLEMENTED

**Evidence:**
- Zero references to ServiceNow, JIRA, Remedy, or ITSM systems
- No external API connectors for ticket systems
- No incident-to-feedback mapping from ITSM data

**Gaps:**
- No ingestion pipeline from ITSM (no API client)
- No correlation of Pedkai decisions with ITSM ticket outcomes
- No CMDB integration (Datagerry is local-only, not production)
- No feedback flow back to ITSM (read-only at best)

---

### Dimension 6: Decision Tracking (Audit Trail)
**Status:** ✅ IMPLEMENTED (Partial)

**Evidence:**
- Reasoning chain tracking (parent_id, derivation_type in decision_traces)
- Immutable feedback audit trail (created_at server-side)
- Composite unique index prevents vote tampering
- RL evaluator recorded with system operator ID
- Recursive CTE queries support full lineage traversal

**Gaps:**
- No explicit audit log table (history mixed with decision data)
- No change tracking for decision attributes (outcome, status updates)
- No soft-delete; can only add data, not revoke
- No audit context (user, timestamp, reason for feedback change)
- Decision status transitions not logged separately

---

## Pipeline Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         FEEDBACK SOURCES                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Operator API                RL Evaluator                        │
│  POST /operator/feedback     Auto-evaluation after:              │
│  POST /{id}/upvote           - Outcome recorded                  │
│  POST /{id}/downvote         - Incident resolved                 │
│         │                              │                         │
│         └──────────────┬───────────────┘                         │
│                        ▼                                         │
│                 Decision Feedback ORM                            │
│              (1 row per operator per decision)                   │
│                        │                                         │
│                        ▼                                         │
│         Aggregate Cache (feedback_score)                         │
│        Updated in decision_traces table                          │
│                        │                                         │
│                        ▼                                         │
│              Similarity Search Boost                             │
│        adjusted_sim = raw_sim + (0.1 * feedback_score)          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘

No downstream flows:
  - ITSM ingestion: NOT CONNECTED
  - Feedback visualization: NOT IMPLEMENTED
  - Behavioral scoring: NOT IMPLEMENTED
  - External audit: NOT CONFIGURED
```

---

## Risk & Recommendation Summary

### High Priority
1. **Operator Identity Gap:** Hardcoded `operator_1` in upvote/downvote endpoints prevents multi-operator aggregation from working correctly
   - **Fix:** Extract actual operator from JWT token or user context

2. **ITSM Isolation:** Feedback loop completely disconnected from incident/ticket systems
   - **Impact:** Decisions made in isolation; no loop closure on business outcomes
   - **Fix:** Implement ServiceNow/JIRA connector to track resolution of incidents linked to decisions

3. **Audit Trail Gaps:** No explicit audit log for who changed what feedback when
   - **Fix:** Add audit_log table with decision_id, old_score, new_score, operator_id, timestamp, reason

### Medium Priority
4. **Behavioral Observation:** Comment field available but unused; no structured observation schema
   - **Fix:** Design assessment rubric and observation template

5. **Decision Tracking:** Reasoning chain exists but not exposed via API
   - **Fix:** Add GET /decisions/{id}/lineage endpoint

6. **Calibration Data:** Stats queried but not used for confidence adjustment
   - **Fix:** Integrate calibration signals into decision scoring

### Low Priority
7. **UI/UX:** No feedback submission interface
8. **Metrics:** No instrumentation on feedback pipeline (volumes, latencies)
9. **Documentation:** No operator guide for feedback submission process

---

## Files Modified in This Session
None. (Audit-only.)

## Summary Statistics
- **Total endpoints:** 3 (1 detailed + 2 shortcuts)
- **Database tables:** 2 (decision_feedback + decision_traces feedback columns)
- **Migrations:** 2 (initial + P3.5 comment field)
- **RL integration points:** 2 (decisions.py + incidents.py)
- **ITSM integration points:** 0
- **Maturity dimensions implemented:** 3/6 (Thumbs up/down, Multi-operator agg, Decision tracking)
