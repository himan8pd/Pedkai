# Strategic Audit: Phases 12–15 (Deep Code Review)

**Reviewer**: Independent Telecom Business Strategist  
**Date**: 11 February 2026  
**Scope**: Vendor deliverables from Phase 12 (Memory Optimization) through Phase 15 (AI Control Plane)  
**Method**: Line-by-line source code inspection of every service, model, test, script, and policy file

---

## Executive Summary

**Overall Score: 5/10 — Architecturally Interesting, Structurally Hollow**

The vendor has delivered a *recognisable shape* of the AI Control Plane vision: a Policy Engine, BSS Integration, RL Evaluator, and CX Intelligence layer now exist as named files with working API plumbing. This is genuine architectural progress.

However, **three systemic failures** recur across every phase:

1. **Security Vulnerability**: The Policy Engine uses Python `eval()` to execute YAML policy conditions — a textbook remote code execution (RCE) vector that would fail any security audit instantly.
2. **"Fallback Theatre"**: Every critical service contains a hardcoded fallback path that returns mock data when no real data is present. Since no real data is seeded in any operational pipeline, these fallbacks are the *only path that ever executes*.
3. **Verification Scripts Verify Themselves**: The test/verification strategy consists primarily of scripts that seed data, then query that data, then assert the data exists. This is a tautology, not a test.

The prior Phase 12-13 review (3/10) prompted genuine remediation. The current Phase 14-15 work was not previously audited and shows the same "scaffolding claimed as substance" pattern from the original Phase 12-13 delivery.

---

## 🔴 CRITICAL FINDINGS

### Finding C-1: Policy Engine Uses `eval()` — Remote Code Execution Risk

**File**: [policy_engine.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/policy_engine.py#L65)  
**Line 65**:
```python
if eval(policy.condition, {"__builtins__": {}}, context):
```

> [!CAUTION]
> **This is an injection attack waiting to happen.** The `condition` string comes from a YAML file, but the `context` dictionary is constructed from user-supplied and network-derived data. An attacker who can influence any value in `context` (e.g. via a crafted alarm payload that populates `service_type` or `customer_tier`) can inject arbitrary Python expressions.
> 
> Setting `__builtins__` to `{}` is a well-known **insufficient** mitigation — it can be bypassed via `__import__`, `type.__subclasses__()`, or attribute chaining. The vendor's own inline comment acknowledges this: `"NOTE: In production, use a safer rule engine like simpleeval"`.

**Severity**: 🔴 CRITICAL — This would be an immediate **P0 rejection** in any enterprise security review.

**Fix**: Replace `eval()` with [simpleeval](https://github.com/danthedeckie/simpleeval) or a proper rule engine (e.g., [business-rules](https://github.com/venmo/business-rules)). Alternatively, implement a whitelist-based condition evaluator that only supports specific operators (`==`, `>`, `<`, `and`, `or`).

---

### Finding C-2: RL Evaluator is Not "Closed-Loop" — It Never Checks KPIs

**File**: [rl_evaluator.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/rl_evaluator.py)  
**Task item**: `[🟡 #15.4] Implement Closed-Loop RL Evaluator` — marked `[x]`

> [!CAUTION]
> **The vision requirement** (from `strategic_master_review.md`, Section 3): *"Implement a `SuccessMetricEvaluator` that automatically checks the TimescaleDB KPIs 30 minutes after an action was taken to verify if the anomaly was actually resolved."*
> 
> **What was delivered**: The evaluator checks `decision.outcome.status == DecisionOutcome.SUCCESS` — a manually-set string. It does **NOT**:
> - Query TimescaleDB to check if KPIs actually improved after the action
> - Schedule any delayed evaluation (no cron, no Celery, no async timer)
> - Compare pre-action and post-action metric baselines
> - Infer success/failure from data
> 
> The "closed loop" is: *a human (or test script) manually sets `outcome.status = SUCCESS`, and the evaluator reads that status*. This is an **open loop with a label**.

**Severity**: 🔴 CRITICAL — This is the core differentiator of Phase 15 and it does not function as described.

**Fix**:
```python
async def evaluate_automatically(self, decision_id: UUID, delay_minutes: int = 30):
    """Schedule KPI check N minutes after action."""
    # 1. Retrieve the decision and its associated entity_id
    # 2. Capture pre-action KPI baseline from TimescaleDB
    # 3. After delay, query post-action KPIs
    # 4. Calculate improvement ratio
    # 5. Set outcome status based on delta threshold
    # 6. Apply reward/penalty automatically
```

---

### Finding C-3: BSS Revenue Fallback Silently Returns $500

**File**: [llm_service.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/llm_service.py#L160)  
**Lines 158-167**:
```python
if any("Gold" in c for c in impacted_customers):
    customer_tier = "GOLD"
predicted_revenue_loss = 500.0  # Mocked fallback
```

> [!WARNING]
> **The BSS integration advertised in Phase 15.1 falls through to a hardcoded $500** revenue-at-risk whenever `impacted_customer_ids` is not provided in the incident context — which is the normal case for most anomaly-triggered flows. Furthermore, the "Gold" tier detection uses a **substring match on customer names** (checking if the string "Gold" appears in a customer name). A customer named "Goldman" would trigger Corporate SLA Priority policies.

**Severity**: 🔴 CRITICAL — Incorrect revenue calculations lead to wrong policy triggers. A $500 default will *never* trigger `POL-003` (Revenue Protection, threshold $10k), making the policy dead code in practice.

**Fix**: 
1. The anomaly pipeline must always resolve `impacted_customer_ids` before reaching the LLM service.
2. Remove all name-based heuristics — use only BSS database lookups.
3. Remove the `$500` hardcoded fallback; if BSS lookup fails, the SITREP should explicitly state "Revenue data unavailable" rather than reporting a fabricated number.

---

## 🟡 HIGH-SEVERITY FINDINGS

### Finding H-1: Benchmark Tests Its Own Seed Data (Tautological)

**File**: [benchmark_memory.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/scripts/benchmark_memory.py)

The remediated benchmark script *does* now calculate real cosine similarity (addressing the previous P12-1 finding). However, it searches for the **same 3 items it seeded**:

```python
# seed_data() inserts GOLD_STANDARD items with embeddings
# run_benchmark() generates query vectors from the SAME descriptions
# Then checks if those exact items are found
```

**Problem**: Searching for `"High PRB utilization causing latency spikes on 5G Cell"` and finding it in a database that *only* contains that exact string does not prove retrieval quality. It proves `cosine_similarity(x, x) ≈ 1.0`.

A real benchmark requires:
- **Distractor items**: 50+ unrelated or subtly-different decisions to test discrimination
- **Paraphrase queries**: Search for "Cell congestion degrading throughput" and expect it to match "High PRB utilization causing latency" 
- **Negative cases**: Queries that should return *nothing* (testing false-positive rates)

**Gold Standard remains at 3 items** vs. the 25+ requested in the prior remediation plan.

---

### Finding H-2: Capacity Engine Has Uniform Costs and Simulated Geography

**File**: [capacity_engine.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/capacity_engine.py#L68-L77)

```python
candidates.append({
    "name": f"Site-{h.entity_id}",
    "lat": 18.5 + (len(candidates) * 0.01),  # Simulated geo-offset
    "lon": 73.8 + (len(candidates) * 0.01),
    "cost": 50000,  # Realistic unit cost
    "pressure": h.avg_value
})
```

**Problems**:
1. **Every site costs exactly $50,000** — there is no cost modelling for fiber vs. microwave backhaul, spectrum type, or urban vs. rural deployment.
2. **Geography is fabricated** — coordinates are generated as arithmetic offsets from a fixed Pune starting point, regardless of the actual region requested.
3. **"Improvement" is a formula, not a prediction**: `(pressure - 0.70) * 100` assumes that adding a site will reduce congestion to 70%, always.
4. **The fallback path (lines 62-66)** still returns hardcoded Pune coordinates when no KPI data exists — which is the default state.

**Fix**: At minimum, the engine should query entity metadata (site location, backhaul type) from the Context Graph rather than fabricating coordinates.

---

### Finding H-3: CX Intelligence Ignores the Context Graph

**File**: [cx_intelligence.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/cx_intelligence.py#L29-L31)

```python
# In a real system, this would involve graph traversal.
site_id = trace.context.get("site_id") if trace.context else None
```

The vendor's **own comment** acknowledges this is a stub. The CX service:
- Matches customers to sites via a static `associated_site_id` column — no graph, no topology awareness
- Does not consider customers who may have been using the affected cell but are "home-sited" elsewhere
- Hardcodes churn threshold at `0.7` with no configuration externalization
- Uses a generic hardcoded care message: `"Proactive alert: We've detected an optimization event in your area."`

The `strategic_review_phase14.md` audit (which the vendor produced themselves) explicitly identified all of these as gaps. They remain unaddressed.

---

### Finding H-4: Deprecated `datetime.utcnow()` Used Across Multiple Files

**Files**: [bss_service.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/bss_service.py#L46) line 46, [decision_repository.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/decision_repository.py#L196) line 196, [bss_orm.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/models/bss_orm.py#L20) line 20

> [!WARNING]
> The walkthrough explicitly claims *"Replaced all `utcnow()` calls with `timezone.utc` aware `now()` objects"* (Phase 11, Audit v4 Hardening). This claim is false. At least 3 files still use `datetime.utcnow()`:

| File | Line | Usage |
|:---|:---|:---|
| `bss_service.py` | 46 | `datetime.utcnow() - timedelta(days=30)` |
| `decision_repository.py` | 196 | `created_at=datetime.utcnow()` |
| `bss_orm.py` | 20 | `default=datetime.utcnow` |

**Fix**: Replace all with `datetime.now(timezone.utc)`.

---

### Finding H-5: LLM Prompt Duplicates Context

**File**: [llm_service.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/llm_service.py#L189-L215)

The SITREP prompt sends `incident_context` **twice** — once as `[NETWORK EVENT]` and again as `[ROOT CAUSE ANALYSIS]`:

```python
prompt = f"""
    [NETWORK EVENT]
    {json.dumps(incident_context, indent=2)}
    
    [ROOT CAUSE ANALYSIS]
    {json.dumps(incident_context, indent=2)}   # <-- Same object!
```

This doubles the token consumption for every LLM call without providing additional information. At scale, this is a direct cost multiplier on the Gemini API bill.

**Fix**: The RCA section should contain the actual RCA output (graph traversal results, dependency chain), not a copy of the raw incident.

---

## 🟡 MEDIUM-SEVERITY FINDINGS

### Finding M-1: No Integration Tests for Phases 14 or 15

**Directory**: [tests/](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/tests)

| Phase | pytest Tests | Verification Scripts |
|:---|:---|:---|
| Phase 12 | ❌ None | `benchmark_memory.py` (tautological) |
| Phase 13 | 1 file, 1 test | `seed_capacity_data.py` |
| Phase 14 | ❌ None | `verify_phase14_cx.py` (seeds + asserts own data) |
| Phase 15 | ❌ None | `verify_rl_evaluator.py`, `verify_bss_integration.py`, `verify_strategy_v2.py` |

The verification scripts are **not pytest tests** — they seed their own data, run the service, and assert on the seeded data. They cannot be integrated into a CI/CD pipeline since they require database connections and don't use test fixtures. No negative-path testing exists anywhere.

**Fix**: Every new service should have corresponding tests in `tests/unit/` or `tests/integration/` using the existing `conftest.py` fixtures. At minimum:
- `test_cx_intelligence.py` — test churn threshold edge cases, missing site_id handling
- `test_policy_engine.py` — test all 4 policies, test invalid conditions, test priority ordering
- `test_rl_evaluator.py` — test reward calculation boundaries, missing outcome handling
- `test_bss_service.py` — test revenue calculation with zero customers, disputes

---

### Finding M-2: Policy Engine Has Only 4 Rules and No Versioning

**File**: [global_policies.yaml](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/policies/global_policies.yaml)

The "Telco Constitution" contains exactly 4 policies. For context, a real Tier-1 operator has hundreds of interconnected business rules. More critically:

- No policy versioning or audit trail (which version was active when a decision was made?)
- No policy conflict resolution (what if POL-002 and POL-004 both match? Both get applied without priority arbitration)
- No time-bounded policies (e.g., "maintenance window" or "peak hour" rules)
- `POL-001` has `action: "ALLOW"` but the engine has no `ALLOW` handler (lines 69-79) — it simply doesn't match any `if` branch, so the policy matches but does nothing
- The `constraints` and `parameters` fields in the YAML are never read by the engine

---

### Finding M-3: Global Singleton Policy Engine Uses Relative Path

**File**: [policy_engine.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/policy_engine.py#L28-L31)

```python
class PolicyEngine:
    def __init__(self, policy_path: str = "backend/app/policies/global_policies.yaml"):
```

The global singleton `policy_engine = PolicyEngine()` at module level means:
1. Policies are loaded at **import time** — any import error in the YAML crashes the entire application
2. The relative path `"backend/app/policies/..."` will only work if the application is started from the project root. Docker containers, K8s pods, or pytest runs from different directories will fail silently (empty policies)
3. Policies cannot be hot-reloaded without restarting the service

---

### Finding M-4: Recursive CTE Chain is N+1 Query

**File**: [decision_repository.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/decision_repository.py#L270-L278)

```python
rows = result.all()
decisions = []
for row in rows:
    # Re-querying by ID might be safer for complex fields like JSON
    d = await self.get_by_id(row.id)
    if d:
        decisions.append(d)
```

The recursive CTE already fetches all columns from `decision_traces`. But then the code **re-queries every row by ID individually** — a classic N+1 problem. For a reasoning chain of depth 10, this means 11 queries (1 CTE + 10 individual lookups). At VJV scale with thousands of decisions, this becomes a performance bottleneck.

---

## 📋 Phase-by-Phase Completion Audit

### Phase 12: Memory Optimization (Post-Remediation)

| Task Item | Claimed | Actual | Evidence |
|:---|:---|:---|:---|
| Gold Standard test cases | ✅ | ⚠️ Partial | Still only 3 items; tautological benchmark |
| Benchmark search parameters | ✅ | ✅ Real math | Cosine similarity with NumPy |
| Fine-tune `min_similarity` | ✅ | ✅ Updated | Config now `0.9` |
| Automated optimization tool | ✅ | ⚠️ Minimal | Iterates thresholds but no grid/Bayesian search |

**Phase 12 Actual Completion: ~60%** (mechanism works, but the dataset is too small to be meaningful)

---

### Phase 13: Capacity Planning (Post-Remediation)

| Task Item | Claimed | Actual | Evidence |
|:---|:---|:---|:---|
| Densification schema | ✅ | ✅ | ORM models present and relational |
| CapEx vs Coverage engine | ✅ | ⚠️ Partial | Queries KPIs, but uniform costs and fake geo |
| Budget constraint | ✅ | ✅ | Greedy algorithm enforces budget |
| Dashboard visualization | ✅ | ⚠️ Unverified | Claimed in walkthrough, frontend not inspectable |

**Phase 13 Actual Completion: ~65%** (budget logic works, but "optimization" is still simplistic)

---

### Phase 14: Customer Experience Intelligence

| Task Item | Claimed | Actual | Evidence |
|:---|:---|:---|:---|
| Churn-to-Anomaly correlation | ✅ | ⚠️ Stub | Simple SQL match on `associated_site_id` |
| Proactive Care automation | ✅ | ⚠️ Stub | Hardcoded message, no LLM, no real notification channel |
| RBAC scopes | ✅ | ✅ | `CX_READ`/`CX_WRITE` properly defined and enforced |

**Phase 14 Actual Completion: ~40%** (plumbing exists, intelligence does not)

---

### Phase 15: AI Control Plane

| Task Item | Claimed | Actual | Evidence |
|:---|:---|:---|:---|
| BSS Data Layer | ✅ | ⚠️ Partial | Models exist, but LLM falls back to $500 mock in practice |
| Policy Engine | ✅ | 🔴 Insecure | Uses `eval()`, only 4 rules, `ALLOW` action is dead code |
| Semantic Context Graph | ✅ | ⚠️ Partial | Recursive CTE works but has N+1 performance issue |
| Closed-Loop RL Evaluator | ✅ | ❌ Not Closed-Loop | Reads manually-set status, does not query post-action KPIs |

**Phase 15 Actual Completion: ~35%** (the "AI Control Plane" label is aspirational, not descriptive)

---

## 🏗️ Recommended Remediation Plan

### Immediate Actions (Sprint 0 — Before Any New Features)

| Priority | Action | Owner | Acceptance Criteria |
|:---|:---|:---|:---|
| 🔴 P0 | Replace `eval()` with `simpleeval` in Policy Engine | Security | No `eval()` calls remain; unit tests for injection payloads |
| 🔴 P0 | Remove ALL `datetime.utcnow()` | Backend | `grep -r "utcnow" backend/` returns zero results |
| 🔴 P0 | Remove $500 hardcoded revenue fallback | Backend | LLM SITREP states "unavailable" if BSS lookup fails |
| 🟡 P1 | Fix LLM prompt duplicate context | Backend | `[ROOT CAUSE ANALYSIS]` section has distinct RCA output |

### Phase 12 Remediation

| Priority | Action | Acceptance Criteria |
|:---|:---|:---|
| 🟡 P1 | Expand Gold Standard to 25+ scenarios with distractors | Dataset includes paraphrases and negative cases |
| 🟡 P2 | Add adversarial queries (subtly different alarms) | False-positive rate measured and reported |

### Phase 14 Remediation

| Priority | Action | Acceptance Criteria |
|:---|:---|:---|
| 🔴 P1 | Implement graph traversal for customer-site correlation | Customers impacted at non-home sites are found |
| 🟡 P2 | Replace hardcoded care message with LLM-powered personalization | Message references specific RCA and customer profile |
| 🟡 P2 | Externalize churn threshold to `config.py` | `churn_risk_threshold: float = 0.7` configurable |

### Phase 15 Remediation

| Priority | Action | Acceptance Criteria |
|:---|:---|:---|
| 🔴 P1 | Implement real KPI delta check in RL Evaluator | Queries TimescaleDB pre/post action, infers outcome |
| 🔴 P1 | Add production-grade policy evaluator | Supports versioning, conflict resolution, audit trail |
| 🟡 P2 | Fix recursive CTE N+1 query | Single CTE query returns all required columns |
| 🟡 P2 | Fix Policy Engine path to use absolute/configurable path | Works from any working directory |
| 🟡 P2 | Handle `ALLOW` action in Policy Engine | Explicit early-exit or priority override logic |

### Testing Remediation

| Priority | Action | Acceptance Criteria |
|:---|:---|:---|
| 🔴 P1 | Create pytest integration tests for Phases 14 and 15 | ≥10 tests per phase in `tests/integration/` |
| 🟡 P2 | Add negative-path tests for Policy Engine | Invalid conditions, missing fields, overflow rewards |
| 🟡 P2 | Convert verification scripts to proper pytest fixtures | All scripts runnable via `pytest tests/ -v` |

---

## Governance Observations

> [!IMPORTANT]
> **Pattern**: The vendor consistently marks task items as `[x]` when the *file* has been created, but before the *logic* has been implemented. This was identified in the Phase 12-13 review, acknowledged, and has recurred in Phases 14-15.
> 
> All 4 task items in Phase 15 are marked complete. By source code evidence:
> - Item 15.1 (BSS): Models exist but the integration path falls through to mocks
> - Item 15.2 (Policy): Has a security vulnerability
> - Item 15.3 (Semantic Graph): CTE works but with performance issues
> - Item 15.4 (RL Evaluator): Does not implement the specified requirement

> [!WARNING]
> **The walkthrough continues to make factual claims contradicted by the codebase** (e.g., the `utcnow()` deprecation claim). This erodes trust with technical reviewers and is a governance risk if these documents are shared with enterprise clients.

---

## Strategic Verdict

The vendor has made **genuine progress** since the Phase 12-13 audit. The BSS data model, Policy Engine concept, RBAC scoping, and recursive reasoning chain are all architecturally sound ideas that move Pedkai toward the AI Control Plane vision.

However, the execution remains in **"Demo Scaffolding"** territory. The critical gap is not the absence of features — it is the **premature completion claims and security defects** that would be caught immediately by any enterprise client's security and architecture review teams.

**Recommendation**: Issue a **conditional hold** on Phase 16+ work. The vendor must first:
1. Fix the `eval()` security vulnerability (non-negotiable)
2. Implement the actual closed-loop KPI check for the RL Evaluator
3. Deliver pytest-based test coverage for Phases 14-15
4. Correct the walkthrough to accurately reflect the codebase state

Only then should new feature work proceed.
