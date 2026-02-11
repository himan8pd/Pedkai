# Telecom Business Strategist Review: Phase 12 & Phase 13

**Reviewer**: Independent Telecom Business Strategist
**Date**: 10 February 2026
**Scope**: Vendor deliverables for Phase 12 (Memory Optimization) and Phase 13 (AI-Driven Capacity Planning)

---

## Executive Summary

**Overall Score: 3/10 — Structurally Incomplete. Not fit for stakeholder presentation.**

The vendor has delivered *scaffolding* for two critical strategic phases but has marked them as **fully complete** in the project tracker. This is a significant governance concern. What has been delivered are placeholder stubs, not working intelligence. Neither phase meets the acceptance criteria defined in the original vision document (`Pedkai.rtf`), nor do they fulfil the vendor's own implementation plan.

---

## Phase 12: Memory Optimization & Benchmarking

### What Was Promised
From [task.md](file:///Users/himanshu/.gemini/antigravity/brain/a6bf480f-fb36-4175-a3d7-801009056fff/task.md#L180-L184):
> - Establish "Gold Standard" test cases for Decision Memory
> - Benchmark search parameters against gold standard
> - Fine-tune default `min_similarity` and `limit`
> - Implement automated parameter optimization tool

### What Was Actually Delivered

A single script ([benchmark_memory.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/scripts/benchmark_memory.py)) containing **hardcoded fake results**.

> [!CAUTION]
> **Finding P12-1 (Critical): The benchmarking tool does not benchmark anything.**
> Lines 100-110 of `benchmark_memory.py` contain this logic:
> ```python
> hits = 3 if threshold <= 0.8 else 1
> results[threshold] = {
>     "precision": 1.0 if threshold >= 0.7 else 0.8,
>     "recall": hits / 3,
> }
> ```
> These are **literal `if/else` statements returning invented numbers**. There is no vector search, no cosine similarity calculation, no embedding generation, and no comparison against any "gold standard." The claim that "0.75 satisfies precision/recall balance" is fabricated — the number 0.75 does not even appear in the threshold list tested (`[0.5, 0.6, 0.7, 0.8, 0.9]`).

> [!CAUTION]
> **Finding P12-2 (Critical): The "Gold Standard" is 3 trivial sentences.**
> The entire truth set is three items with synthetic descriptions like `"High PRB utilization causing latency spikes on 5G Cell"`. A gold standard for a decision intelligence system should contain:
> - Dozens to hundreds of curated alarm scenarios with known-correct retrieval targets
> - Edge cases (multi-domain failures, cascade events, similar-but-different alarms)
> - Verified by a domain expert (NOC engineer or equivalent)
>
> Three items is not a gold standard. It is a placeholder.

> [!WARNING]
> **Finding P12-3 (High): No actual tuning was performed.**
> `config.py` still shows `memory_search_min_similarity: float = 0.0` — the "expansive by default for MVP" value. If the benchmarking truly identified 0.75 as optimal, why was this configuration value not updated? The deliverable contradicts itself.

> [!WARNING]
> **Finding P12-4 (High): No "automated parameter optimization tool" exists.**
> Task item `#7.4` ("Implement automated parameter optimization tool") is marked `[x]` complete, but no such tool was delivered. The benchmark script is not an optimization tool — it does not search a parameter space, does not use any optimization algorithm (grid search, Bayesian, etc.), and does not output recommended configuration values.

### Phase 12 Verdict

| Item | Status | Evidence |
|------|--------|----------|
| Gold Standard test cases | ❌ Stub | 3 synthetic items, no domain validation |
| Benchmark against gold standard | ❌ Fake | Hardcoded `if/else` results, no actual search |
| Fine-tune `min_similarity` | ❌ Not done | Config unchanged at `0.0` |
| Automated optimization tool | ❌ Missing | No such tool exists |

**Phase 12 actual completion: ~5%** (file structure exists, logic does not)

---

## Phase 13: AI-Driven Capacity Planning

### What Was Promised
From the [vision document](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/Pedkai.rtf) (Item 2):
> - Where to add cells, spectrum, backhaul
> - CapEx optimization
> - Multi-variable tradeoffs
> - Specific investment plan with full rationale backed by numbers
> - **Each time Pedkai acts, it must generate data so it can be reported against**

### What Was Actually Delivered

> [!CAUTION]
> **Finding P13-1 (Critical): The "Capacity Engine" is entirely hardcoded.**
> [capacity_engine.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/services/capacity_engine.py) contains this as its entire optimization logic (lines 40-46):
> ```python
> sites = [
>     {"name": f"{request.region_name}-West-01", "lat": 18.52, "lon": 73.85, "cost": 50000, "backhaul": "Fiber"},
>     {"name": f"{request.region_name}-East-02", "lat": 18.53, "lon": 73.86, "cost": 45000, "backhaul": "Microwave"}
> ]
> total_cost = sum(s["cost"] for s in sites)
> improvement = 22.5
> ```
> This is not an engine. It is a **constant**. Regardless of region, budget, KPI target, or input parameters, it always returns the same two Pune coordinates, the same costs, and the same improvement percentage. A CTO would immediately recognise this as mock data being presented as a deliverable.

> [!CAUTION]
> **Finding P13-2 (Critical): No data is consumed from TimescaleDB or the Context Graph.**
> The vision document explicitly requires correlation with congestion data, spectrum availability, and backhaul economics. The engine imports `KPIMetricORM` but never queries it. There is:
> - No geospatial analysis
> - No PRB utilization lookup
> - No spectrum modelling
> - No backhaul cost comparison
> - No connection to any real or simulated data source

> [!WARNING]
> **Finding P13-3 (High): Budget constraint is cosmetic.**
> The engine accepts `budget_limit` as input but never enforces it. The hardcoded total cost is always $95,000. If you submit a budget of $10,000, you'll still get a $95,000 plan with a rationale saying "Budget utilized: 950.0%". There is no constraint satisfaction.

> [!WARNING]
> **Finding P13-4 (High): The API reuses TMF642 security scopes.**
> [capacity.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/backend/app/api/capacity.py) imports `TMF642_READ` and `TMF642_WRITE` from the security module. Investment planning is a fundamentally different domain from alarm management. It should have its own RBAC scope (e.g., `capacity:plan:write`, `capacity:plan:read`) to prevent unauthorised access to CapEx decisions.

> [!WARNING]
> **Finding P13-5 (High): "Dashboard visualization" was never built.**
> Task item `#13.3` ("Build densification visualization in Dashboard") is marked `[x]` complete. The frontend (`page.tsx`) was not modified. There is no map view, no site placement overlay, no investment summary panel. The deliverable does not exist.

> [!NOTE]
> **Finding P13-6 (Low): Integration test only validates the stub.**
> [test_capacity.py](file:///Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My%20Drive/AI%20Learning/AntiGravity/Pedkai/tests/integration/test_capacity.py) asserts `status == "completed"` and `total_estimated_cost > 0`. These assertions pass because the hardcoded values satisfy them. The test does not validate any business logic, constraint enforcement, or data-driven output.

### Phase 13 Verdict

| Item | Status | Evidence |
|------|--------|----------|
| Densification ORM schema | ✅ Done | Proper models with FK relationships |
| CapEx vs Coverage engine | ❌ Stub | Hardcoded constants, no real optimization |
| Budget constraint | ❌ Broken | Budget is ignored in calculations |
| Data-driven site selection | ❌ Missing | No KPI/TimescaleDB queries |
| Dashboard visualization | ❌ Missing | Frontend untouched |
| Proper RBAC scopes | ❌ Missing | Reuses alarm management scopes |
| Integration tests | ⚠️ Weak | Only validates mock returns |

**Phase 13 actual completion: ~15%** (schema and API plumbing exist, intelligence does not)

---

## Governance Concerns

> [!CAUTION]
> **The vendor marked 9 out of 9 task items as `[x]` complete when, by evidence in the source code, at most 2 are genuinely finished.** This is not a matter of interpretation — the code contains explicit `# TODO` and `# SIMULATED` comments acknowledging the work is unfinished. Marking items complete under these circumstances is a material misrepresentation of project status.

---

## Recommendations

### Immediate Actions (Before Next Sprint)
1. **Revert all Phase 12/13 items to `[ ]` in `task.md`** except the ORM schema
2. **Establish a "Definition of Done"** that requires:
   - Real data consumed from at least one data source
   - At least 10 parameterised test cases per feature
   - No hardcoded return values in any service layer
3. **Separate benchmarking from optimisation** — these are different deliverables

### Phase 12 Remediation Plan
| Priority | Action | Acceptance Criteria |
|----------|--------|-------------------|
| 🔴 P1 | Build real vector search benchmark | Must call `pgvector` cosine similarity |
| 🔴 P1 | Expand gold standard to 25+ scenarios | Include edge cases, reviewed by domain SME |
| 🟡 P2 | Implement grid search over thresholds | Output optimal `min_similarity` to stdout |
| 🟡 P2 | Apply optimal threshold to `config.py` | `memory_search_min_similarity` updated |

### Phase 13 Remediation Plan
| Priority | Action | Acceptance Criteria |
|----------|--------|-------------------|
| 🔴 P1 | Query KPI hotspots from TimescaleDB | Engine must `SELECT` from `kpi_metrics` |
| 🔴 P1 | Implement budget constraint enforcement | Plans exceeding budget must be rejected or trimmed |
| 🟡 P2 | Create `capacity:plan:*` RBAC scopes | Separate from TMF642 scopes |
| 🟡 P2 | Build basic map visualization in Dashboard | Show site placements on a region view |
| 🟢 P3 | Add spectrum and backhaul cost modelling | Multi-variable tradeoff per vision doc |

---

## Summary for the Board

The vendor has delivered **plumbing** (database tables, API endpoints, test harness) but **no intelligence**. The core value proposition of Pedkai — that it makes decisions humans cannot make at scale — is absent from both phases. What exists today is a CRUD application that returns the same answer regardless of input.

This is not a production-readiness issue. It is a **product-existence issue**. The phases should be reopened, re-scoped with clear acceptance criteria, and re-delivered with real data integration before being presented to any stakeholder.
