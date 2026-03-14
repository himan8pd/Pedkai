# NEW_TASKS.md — Pedk.ai Atomic Task Backlog
**Generated from:** `PRODUCT_SPEC.md` v2.0 (2026-03-05)  
**Methodology:** Erdos AI Enterprise AI Deployment Framework  
**Scope:** All outstanding work to bring backlog to zero  
**Agent Target:** Tasks are written for atomic execution by a low-level agent (Claude Haiku or equivalent)

---

## HOW TO READ THIS FILE

Each task is:
- **Atomic** — one deliverable, one agent, one completion state
- **Testable** — has explicit pass/fail acceptance criteria
- **Self-contained** — carries all context needed to execute without reading other files
- **Phased** — phases indicate execution order; tasks within a phase may run in parallel unless a `Depends On` field says otherwise

**Maturity symbols used in spec (for reference):**
- ✅ Implemented | ⚠️ Partial | 🔨 In Progress | 📋 Planned | 🔮 Future | ❌ Not implemented

---

## PHASE MAP

| Phase | Name | Can Parallelise? | Blocks |
|-------|------|:----------------:|--------|
| **0** | Audit & Baseline | ✅ Full parallel | Nothing — these are reads only |
| **1** | Critical Fixes — Dead Code & Broken Wiring | ✅ Full parallel | Phases 2+ |
| **2** | Synthetic Data Realism | ✅ Full parallel within project | Phase 3 ML tasks |
| **3** | Core Engine Upgrades | ⚠️ Partial — some serial within stream | Phase 4 |
| **4** | Operator Experience & Feedback | ⚠️ Partial | Phase 5 |
| **5** | Governance, Compliance & Documentation | ✅ Full parallel | Phase 6 |
| **6** | Integration, Validation & Training | Serial — integration dependent | Ship |

---

## PHASE 0 — AUDIT & BASELINE
> **Goal:** Establish ground truth of current codebase state before any changes. All tasks read-only. Run all in parallel.

---

### TASK-001: Audit sleeping cell detector wiring
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-024  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
The product spec (§6, Feature 2) states that sleeping cell detection code exists but is "not wired into scheduler." The `main.py` scheduler does not invoke the sleeping cell detector, making it dead code. Before fixing this (TASK-101), you must locate the exact files, function signatures, and scheduler call site.

#### Deliverables
- [ ] `audit/sleeping_cell_wiring.md` — a markdown file containing:
  - Full file path of the sleeping cell detector module
  - All function/class names in that module
  - Full file path of `main.py` (or equivalent scheduler entry point)
  - The exact line number and code block in the scheduler where the call should be inserted
  - List of any imports needed

#### Acceptance Criteria
- [ ] File exists at `audit/sleeping_cell_wiring.md`
- [ ] File names are verified by checking they exist in the repo (`os.path.exists`)
- [ ] Line numbers reference actual code (grep-verifiable)

#### Implementation Notes
Run `find . -type f -name "*.py" | xargs grep -l "sleeping_cell\|SleepingCell\|sleeping cell" -i` to locate the module. Run `grep -n "scheduler\|schedule\|asyncio\|APScheduler\|celery" main.py` to find scheduler call sites.

---

### TASK-002: Audit Dark Graph module completeness
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-025  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§6 Feature 1 (Dark Graph Reconciliation) lists the following capabilities as "🔨 In Progress": Divergence Report, Datagerry CMDB sync adapter, CasinoLimit telemetry parser, Topological Ghost Masks. You need to know exactly what exists vs what is missing before writing any code.

#### Deliverables
- [ ] `audit/dark_graph_completeness.md` containing:
  - For each of the 4 in-progress capabilities: file paths, function names, and a one-line status (exists/stub/missing)
  - The schema/fields of `divergence_manifest.parquet` if it exists, or "NOT FOUND"
  - List of files in the `dark_graph/` or equivalent directory (or "directory not found")
  - The Datagerry API endpoint(s) the adapter is meant to call (from any existing config or README)

#### Acceptance Criteria
- [ ] All 4 capabilities have a clear status
- [ ] At least one concrete file path is listed per capability (or "NOT FOUND" with grep evidence)

---

### TASK-003: Audit Abeyance Memory implementation gaps
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-016, T-026  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§4 Engineering Maturity table shows: vector storage ✅, semantic similarity snapping ✅, multi-modal matching ⚠️ partial, long-horizon retrieval ⚠️ partial, abeyance decay ❌ not implemented. You need to find the exact state of each gap in code.

#### Deliverables
- [ ] `audit/abeyance_memory_gaps.md` containing:
  - File path of the Abeyance Memory / vector store module
  - Current TTL / retention logic (if any — grep for "TTL\|ttl\|decay\|expire\|retention" in the module)
  - The pgvector table schema (column names, embedding dimension)
  - Current cold storage retrieval code (or "NOT IMPLEMENTED")
  - Current telemetry-to-text alignment code (or "NOT IMPLEMENTED")

#### Acceptance Criteria
- [ ] All 5 maturity dimensions from §4 have a clear code-level status (file + function or "missing")
- [ ] pgvector table name is identified

---

### TASK-004: Audit operator feedback pipeline gaps
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-003, T-007  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§7 Engineering Maturity table shows: thumbs up/down ✅, multi-operator aggregation ✅, behavioural observation ❌, structured assessment ❌, ITSM ingestion ❌, decision tracking ⚠️. You need exact file paths and what the implemented items look like.

#### Deliverables
- [ ] `audit/feedback_pipeline_gaps.md` containing:
  - File path and schema of `DecisionFeedbackORM` (junction table)
  - Current feedback API endpoint(s) — path, method, request/response schema
  - Any existing ITSM integration code (or "NOT FOUND")
  - The RL evaluator file path and its current wiring status

#### Acceptance Criteria
- [ ] `DecisionFeedbackORM` schema fully documented
- [ ] Each of the 6 maturity dimensions has a code reference or "NOT FOUND"

---

### TASK-005: Audit evidence fusion and causal inference modules
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-017, T-023  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§5 describes Noisy-OR as the current evidence fusion method. §8 describes Granger Causality as the current causal inference method. Both need to become pluggable (T-017 = FusionMethodologyFactory, T-023 = causal inference selection). You need to find and document the current implementation before refactoring.

#### Deliverables
- [ ] `audit/fusion_and_causal.md` containing:
  - File path and class/function name of the Noisy-OR implementation
  - File path and class/function name of the Granger Causality implementation
  - Current interface signature for both (input types → output types)
  - Any existing abstract base class or interface (or "none")
  - Dependencies (Python packages) used by each

#### Acceptance Criteria
- [ ] Both implementations located with file paths and function signatures
- [ ] Dependency list complete (runnable `pip install` would satisfy them)

---

### TASK-006: Audit synthetic data generator current state
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 0  
**Original Ref:** T-018, T-019, T-020, T-021, T-022  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§10 describes the synthetic data generator producing ~12.2 GB across 17 Parquet files. It has 5 known quality issues: UUID V4 overuse, scenario realism, temporal realism (AR(1) only), alarm correlation chains, and CMDB degradation patterns. You need to find the current generator code before fixing any of them.

#### Deliverables
- [ ] `audit/synthetic_data_state.md` containing:
  - File paths of all generator scripts
  - The function/class responsible for entity identifier generation (grep for `uuid4\|UUID\|uuid.uuid4`)
  - The function responsible for KPI time-series generation (grep for `AR\|ar_model\|autoregressive\|np.random`)
  - The function responsible for fault/scenario injection (grep for `inject\|fault\|sleeping_cell\|anomaly`)
  - The function responsible for CMDB degradation (grep for `decommission\|phantom\|dark_node\|diverge`)
  - List of the 17 Parquet file names and their approximate row counts (from existing README or by listing `/data/` directory)

#### Acceptance Criteria
- [ ] All 5 quality issues have a code-level location identified
- [ ] All 17 Parquet files are listed

---

### TASK-007: Audit frontend architecture
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-027  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§17 task T-027 says "Frontend decomposition: split monolithic `page.tsx` into routed pages." You need to understand the current structure before decomposing it.

#### Deliverables
- [ ] `audit/frontend_architecture.md` containing:
  - Full directory listing of the Next.js frontend (`frontend/` or `app/` directory)
  - Line count of `page.tsx` (`wc -l frontend/app/page.tsx` or equivalent)
  - List of all React components currently defined in `page.tsx` (grep for `function\|const.*=.*().*=>`)
  - Current routes defined (if any) in `next.config.js` or `app/` directory structure
  - List of all API calls made from the frontend (grep for `fetch\|axios\|api/`)

#### Acceptance Criteria
- [ ] `page.tsx` line count documented
- [ ] All components and API calls listed

---

### TASK-008: Audit test suite coverage
**Project:** Pedk.ai  
**Phase:** 0  
**Original Ref:** T-028  
**Depends On:** Nothing  
**Parallel With:** All other Phase 0 tasks  

#### Context
§17 task T-028 says "Phase 5 test suite: expand from ~5 trivial tests to comprehensive safety gate coverage." You need to know what exists before writing new tests.

#### Deliverables
- [ ] `audit/test_coverage.md` containing:
  - Full list of existing test files (find `tests/` directory)
  - Number of test functions in each file (`grep -c "def test_" filename`)
  - Which modules have zero test coverage (compare `src/` against `tests/`)
  - The 7 safety gates mentioned in §3 Layer 5 — list each gate name/description as found in code (grep for `safety_gate\|SafetyGate\|gate_`)
  - Current test command (`pytest` invocation from README or Makefile)

#### Acceptance Criteria
- [ ] Total existing test count documented
- [ ] All 7 safety gates located in code (or "NOT FOUND" per gate)
- [ ] Coverage gaps list complete

---

## PHASE 1 — CRITICAL FIXES: DEAD CODE & BROKEN WIRING
> **Goal:** Fix the highest-priority broken items that make the product non-functional. All tasks in Phase 1 are independent and can run in parallel. **Requires Phase 0 audit outputs.**

---

### TASK-101: Wire sleeping cell detector into scheduler
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-024  
**Depends On:** TASK-001  
**Parallel With:** TASK-102 through TASK-107  

#### Context
The sleeping cell detector (§6 Feature 2) uses 6 detection methods: zero-user baseline comparison, neighbour-reference Z-score, KPI correlation breakpoint detection, deep autoencoder reconstruction error, MDT-based triangulation, and traffic handover asymmetry. The code exists but is not called by the scheduler in `main.py`, making it dead code. The audit in TASK-001 identified the exact insertion point.

The scheduler must call the detector on a configurable interval (default: every 15 minutes, matching typical NOC refresh cycles). The detector result must be logged as a structured JSON event and, if sleeping cells are found, create a `DecisionTraceORM` record.

#### Deliverables
- [ ] Modified `main.py` (or equivalent scheduler file) with sleeping cell detector registered as a scheduled job
- [ ] New environment variable `SLEEPING_CELL_INTERVAL_MINUTES` (default: `15`) controlling run frequency
- [ ] Unit test `tests/test_sleeping_cell_wiring.py` with at minimum:
  - Test that the scheduler job exists and is registered
  - Test that calling the detector with a mock KPI dataset returns a structured result (not None, not exception)
  - Test that a sleeping cell detection event creates a `DecisionTraceORM` record

#### Acceptance Criteria
- [ ] `pytest tests/test_sleeping_cell_wiring.py` passes with 0 failures
- [ ] Running `main.py` for 1 simulated cycle does not raise an exception
- [ ] A sleeping cell in the synthetic test data triggers a log entry with `"event": "sleeping_cell_detected"` and the cell ID

#### Implementation Notes
From the audit output (TASK-001), use the exact file paths and function signatures found. Register using the same scheduler pattern already used for other jobs in `main.py`. Do not refactor the detector itself — only wire it in.

---

### TASK-102: Implement Abeyance Memory decay scoring
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-016  
**Depends On:** TASK-003  
**Parallel With:** TASK-101, TASK-103 through TASK-107  

#### Context
§4 Engineering Maturity: "Abeyance decay and relevance scoring — ❌ Not implemented." Stale fragments currently persist indefinitely in the pgvector store. Without decay, the Abeyance Memory accumulates noise — an engineer's fragment from 3 years ago about a decommissioned node should not compete equally with a fragment from last week about an active node.

Decay must be relevance-weighted, not just time-based: a fragment corroborated by multiple independent evidence sources should decay more slowly than an isolated fragment. The decay score must be stored as a column on the Abeyance Memory table.

**Formula to implement:**
```
decay_score(t) = base_relevance × exp(-λ × days_since_created) × corroboration_multiplier
```
Where:
- `base_relevance` = 1.0 at creation
- `λ` = configurable decay constant (default: `0.05` ≈ half-life of ~14 days for isolated fragments)
- `corroboration_multiplier` = `1 + (0.3 × corroboration_count)` (each corroboration slows decay)
- Fragments with `decay_score < 0.05` are marked `status = 'STALE'` and excluded from similarity search

#### Deliverables
- [ ] New column `decay_score FLOAT NOT NULL DEFAULT 1.0` on the Abeyance Memory pgvector table (Alembic migration)
- [ ] New column `corroboration_count INTEGER NOT NULL DEFAULT 0` on same table
- [ ] New column `status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'` (values: ACTIVE, STALE, RESOLVED)
- [ ] `AbeyanceDecayService` class in `services/abeyance_decay.py` with:
  - `compute_decay(fragment_id: UUID) -> float` method
  - `run_decay_pass(tenant_id: UUID) -> dict` method (batch update all fragments, return count updated)
  - `mark_stale_fragments(tenant_id: UUID, threshold: float = 0.05) -> int` method
- [ ] Scheduler registration: decay pass runs every 6 hours (env var `ABEYANCE_DECAY_INTERVAL_HOURS`, default: `6`)
- [ ] Tests in `tests/test_abeyance_decay.py`:
  - Test: fragment created today has `decay_score` close to 1.0
  - Test: fragment created 28 days ago (mocked) with no corroboration has `decay_score < 0.15`
  - Test: fragment with `corroboration_count = 5` decays slower than one with `corroboration_count = 0`
  - Test: `mark_stale_fragments` correctly marks fragments below threshold

#### Acceptance Criteria
- [ ] Alembic migration runs without error on a clean database
- [ ] `pytest tests/test_abeyance_decay.py` passes with 0 failures
- [ ] `decay_score` is excluded from similarity search queries when `status = 'STALE'`
- [ ] Decay pass is registered in scheduler and runs on interval

---

### TASK-103: Replace UUID V4 identifiers in synthetic data generator
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 1  
**Original Ref:** T-018  
**Depends On:** TASK-006  
**Parallel With:** TASK-101, TASK-102, TASK-104 through TASK-107  

#### Context
§10 Quality Issue: "UUID V4 overuse — Real operators use human-friendly IDs (e.g., `LTE-8842-A`, `SITE-NW-1847`, `WO-2024-NW-1847`)." Pedk.ai's Dark Graph reconciliation code will be tuned against synthetic data. If entity IDs look nothing like real IDs, the reconciliation engine learns wrong patterns.

**Real operator ID patterns to implement:**
- Cell IDs: `{VENDOR_PREFIX}-{SITE_ID}-{CELL_TYPE}-{CELL_NUM}` e.g., `ERB-8842-LTE-1`, `NOK-3921-NR-3`
- Site IDs: `SITE-{PROVINCE_CODE}-{SEQUENCE}` e.g., `SITE-JKT-1847`, `SITE-BJN-0042`
- Work orders: `WO-{YEAR}-{PROVINCE_CODE}-{SEQUENCE}` e.g., `WO-2024-JKT-18472`
- Alarm IDs: `ALM-{UNIX_TIMESTAMP}-{VENDOR_PREFIX}-{SEQUENCE}` e.g., `ALM-1703123456-ERB-0001`
- CMDB CI IDs: `CI-{TYPE_CODE}-{SITE_ID}-{SEQUENCE}` e.g., `CI-RRU-SITE-JKT-1847-001`

Use the 38 Indonesian province codes from the existing generator data (since the generator uses Indonesian provinces). Province codes should match ISO 3166-2:ID format (e.g., `JK` for Jakarta, `JT` for Jawa Tengah).

#### Deliverables
- [ ] New module `generators/id_factory.py` with functions:
  - `generate_cell_id(vendor: str, site_id: str, cell_type: str, cell_num: int) -> str`
  - `generate_site_id(province_code: str, sequence: int) -> str`
  - `generate_work_order_id(year: int, province_code: str, sequence: int) -> str`
  - `generate_alarm_id(timestamp: int, vendor: str, sequence: int) -> str`
  - `generate_cmdb_ci_id(type_code: str, site_id: str, sequence: int) -> str`
  - `PROVINCE_CODES: dict` mapping province names to 2-letter codes for all 38 provinces
- [ ] Updated generator scripts to use `id_factory.py` instead of `uuid.uuid4()`
- [ ] Collision-safe generation: each function must guarantee uniqueness within a generation run (use a monotonic sequence counter, not random)
- [ ] Tests in `tests/test_id_factory.py`:
  - Test: 10,000 generated cell IDs are all unique
  - Test: ID format matches expected regex pattern per type
  - Test: province codes are all valid (in `PROVINCE_CODES` dict)
  - Test: regenerating the same parameters produces the same ID (deterministic)

#### Acceptance Criteria
- [ ] `pytest tests/test_id_factory.py` passes
- [ ] A sample output of 100 generated entity IDs contains zero UUID V4 strings (regex: `[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}`)
- [ ] Existing generator can be run end-to-end without errors after the change

---

### TASK-104: Build FusionMethodologyFactory skeleton
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-017  
**Depends On:** TASK-005  
**Parallel With:** TASK-101, TASK-102, TASK-103, TASK-105 through TASK-107  

#### Context
§5 states: "Product roadmap item: Implement a `FusionMethodologyFactory` that selects the appropriate evidence fusion engine at deployment configuration time. V1 ships with Noisy-OR. V2 adds Dempster-Shafer for sparse-evidence deployments."

The factory must be an **Abstract Factory** pattern. The existing Noisy-OR implementation (found in audit TASK-005) must be refactored to implement the abstract interface WITHOUT changing its current behaviour.

**The interface contract:**
```python
class EvidenceFusionMethodology(ABC):
    @abstractmethod
    def combine(self, evidence_probabilities: list[float]) -> float:
        """Combine independent evidence probabilities into a single hypothesis confidence."""
        pass
    
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def is_appropriate_for(self, evidence_profile: EvidenceProfile) -> bool:
        """Self-report whether this methodology suits the given evidence profile."""
        pass
```

`EvidenceProfile` is a simple dataclass: `source_count: int, is_sparse: bool, has_qualitative_assessments: bool, has_rich_telemetry: bool`.

#### Deliverables
- [ ] `services/fusion/base.py` — abstract base class `EvidenceFusionMethodology` and `EvidenceProfile` dataclass
- [ ] `services/fusion/noisy_or.py` — existing Noisy-OR logic refactored to implement the interface (no behaviour change)
- [ ] `services/fusion/factory.py` — `FusionMethodologyFactory` class with:
  - `register(name: str, methodology: Type[EvidenceFusionMethodology])` class method
  - `create(name: str) -> EvidenceFusionMethodology` class method
  - `select_for_profile(profile: EvidenceProfile) -> EvidenceFusionMethodology` class method (auto-selects based on profile)
  - Pre-registered: `"noisy_or"` → `NoisyORFusion`
- [ ] `FUSION_METHODOLOGY` environment variable (default: `"noisy_or"`) read at startup to configure the active methodology
- [ ] Tests in `tests/test_fusion_factory.py`:
  - Test: factory returns NoisyOR when `FUSION_METHODOLOGY=noisy_or`
  - Test: NoisyOR output for known inputs matches pre-refactor output (regression test — compute expected value before refactoring)
  - Test: `select_for_profile` returns NoisyOR for rich telemetry profile
  - Test: registering a custom methodology and retrieving it

#### Acceptance Criteria
- [ ] `pytest tests/test_fusion_factory.py` passes
- [ ] All existing evidence fusion call sites updated to use `FusionMethodologyFactory.create()` — no direct `NoisyOR` instantiation in non-test code
- [ ] Noisy-OR output for a known input (`[0.7, 0.8, 0.6]`) is identical before and after refactor: `1 - (1-0.7)(1-0.8)(1-0.6) = 0.976`

---

### TASK-105: Implement Dempster-Shafer evidence fusion
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-017  
**Depends On:** TASK-104  
**Parallel With:** TASK-101 through TASK-103, TASK-106, TASK-107  

#### Context
§5 recommends Dempster-Shafer Theory (DST) for sparse-evidence environments — specifically for Type 3 (secure infrastructure) and Type 4 (multi-party handover) divergences where evidence is partial and ignorance is a valid state.

DST assigns belief masses to *sets* of hypotheses, not single hypotheses. For Pedk.ai's binary use case (hypothesis is TRUE or FALSE), the frame of discernment Θ = {TRUE, FALSE}. A body of evidence assigns:
- `m({TRUE})` — belief that the hypothesis is definitively true
- `m({FALSE})` — belief that the hypothesis is definitively false  
- `m(Θ)` — ignorance (neither true nor false confirmed)

These must sum to 1.0. Dempster's combination rule combines two bodies of evidence. The implementation should use the **Yager normalisation** variant to handle high-conflict evidence gracefully (conflict mass flows to ignorance rather than being renormalised, which avoids the counter-intuitive results of original Dempster's rule).

#### Deliverables
- [ ] `services/fusion/dempster_shafer.py` implementing `EvidenceFusionMethodology`:
  - `combine(evidence_probabilities: list[float]) -> float` — converts each probability to a mass function, applies Yager combination rule iteratively, returns `m({TRUE})` of the combined result
  - Handles edge cases: empty list returns 0.0; single element returns that element; conflicting evidence (sum > 1.0) handled via Yager normalisation
  - `is_appropriate_for(profile: EvidenceProfile) -> bool` — returns True when `profile.is_sparse = True`
- [ ] `DempsterShaferFusion` registered in `FusionMethodologyFactory` as `"dempster_shafer"`
- [ ] Tests in `tests/test_dempster_shafer.py`:
  - Test: two agreeing evidence sources (0.8, 0.9) produces higher confidence than either alone
  - Test: completely ignorant evidence (0.5 = maximum uncertainty) produces correct mass distribution
  - Test: highly conflicting evidence does not produce counter-intuitive result (Yager handles gracefully)
  - Test: factory creates correct implementation for sparse profile

#### Acceptance Criteria
- [ ] `pytest tests/test_dempster_shafer.py` passes
- [ ] For inputs `[0.8, 0.7]` (agreeing): result > 0.9
- [ ] For single input `[0.5]` (maximum ignorance): result = 0.5 (no artificial confidence boost)
- [ ] No dependency on `pyds` or other DST libraries — pure Python implementation

---

### TASK-106: Implement Transfer Entropy causal inference
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-023  
**Depends On:** TASK-005  
**Parallel With:** TASK-101 through TASK-105, TASK-107  

#### Context
§8 recommends Transfer Entropy (TE) as the V2 upgrade to Granger Causality. TE is information-theoretic: it measures how much knowing the past of X reduces uncertainty in the future of Y, capturing **non-linear** dependencies that Granger (linear VAR model) misses.

TE(X→Y) = H(Y_future | Y_past) - H(Y_future | Y_past, X_past)  
Where H is Shannon entropy. Values > 0 indicate X has causal influence on Y.

Implementation uses **kernel density estimation** (KDE) or **k-nearest neighbours** (KNN) for entropy estimation — use KNN (Kraskov estimator) as it is more robust for small samples. The `jpype` + `infodynamics` Java library approach should be avoided — use pure Python with `scipy` and `sklearn`.

The existing Granger Causality implementation must continue to work. This is an **addition**, not a replacement.

#### Deliverables
- [ ] `services/causal/base.py` — abstract `CausalInferenceMethod(ABC)` with `compute(x: np.ndarray, y: np.ndarray, lag: int) -> CausalResult` where `CausalResult = dataclass(score: float, p_value: float, is_causal: bool, method: str)`
- [ ] `services/causal/granger.py` — existing Granger implementation refactored to implement interface (no behaviour change)
- [ ] `services/causal/transfer_entropy.py` — KNN-based Transfer Entropy implementing the interface:
  - Kraskov-1 entropy estimator using `sklearn.neighbors.NearestNeighbors`
  - `lag` parameter controls how many past timesteps of X are used
  - Significance testing via permutation test (100 permutations by default, configurable via `TE_PERMUTATION_COUNT` env var)
  - `p_value` is the fraction of permuted TE values that exceed the observed TE
- [ ] `services/causal/factory.py` — `CausalMethodFactory` mirroring `FusionMethodologyFactory` pattern
- [ ] `CAUSAL_METHOD` environment variable (default: `"granger"`)
- [ ] Tests in `tests/test_transfer_entropy.py`:
  - Test: TE(X→Y) > TE(Y→X) when X is constructed to cause Y (e.g., Y_t = X_{t-1} + noise)
  - Test: TE ≈ 0 for two independent random series
  - Test: permutation test produces `p_value < 0.05` for causal pair, `p_value > 0.05` for independent pair
  - Test: factory creates correct implementation

#### Acceptance Criteria
- [ ] `pytest tests/test_transfer_entropy.py` passes
- [ ] For a known causal pair (X causes Y with lag=1): `is_causal = True` and `p_value < 0.05`
- [ ] For two i.i.d. Gaussian series: `is_causal = False` with `p_value > 0.1`
- [ ] Runtime for 1000-sample series with 100 permutations: < 5 seconds

---

### TASK-107: Implement persistent event bus (Redis-backed queue)
**Project:** Pedk.ai  
**Phase:** 1  
**Original Ref:** T-008  
**Depends On:** Nothing (but see TASK-001 output to avoid duplicate scheduler registration)  
**Parallel With:** TASK-101 through TASK-106  

#### Context
§14 Lens 2 — Operationalisation score: 2/5. "In-process state won't survive scale-out." Currently the system uses `asyncio.Queue` for internal event routing. Under Kubernetes horizontal pod autoscaling, two pods cannot share an `asyncio.Queue`, meaning events are silently lost during scale-out.

Redis Streams (`XADD`/`XREAD`/`XACK`) are the target implementation — they provide persistent, ordered, consumer-group-based event delivery that survives pod restarts and supports multiple consumers.

**Event types to route through the bus:**
1. `anomaly.detected` — payload: `{tenant_id, entity_id, metric, z_score, timestamp}`
2. `sleeping_cell.detected` — payload: `{tenant_id, cell_id, detection_method, confidence, timestamp}`
3. `dark_graph.divergence_found` — payload: `{tenant_id, divergence_type, entity_id, confidence, timestamp}`
4. `operator.feedback_received` — payload: `{tenant_id, decision_id, operator_id, feedback_type, timestamp}`
5. `abeyance.snap_occurred` — payload: `{tenant_id, fragment_id_a, fragment_id_b, similarity_score, timestamp}`

#### Deliverables
- [ ] `services/event_bus.py` with `EventBus` class:
  - `publish(event_type: str, payload: dict, tenant_id: UUID) -> str` — returns event ID
  - `subscribe(event_type: str, consumer_group: str, consumer_name: str) -> Iterator[Event]` — yields events
  - `acknowledge(event_type: str, consumer_group: str, event_id: str) -> None`
  - `get_pending_count(event_type: str, consumer_group: str) -> int`
  - Falls back to `asyncio.Queue` when `REDIS_URL` env var is not set (for local dev without Redis)
- [ ] All existing `asyncio.Queue` usages replaced with `EventBus.publish` / `EventBus.subscribe` calls
- [ ] Docker Compose dev file updated to include Redis service
- [ ] Kubernetes Helm chart updated with Redis dependency and `REDIS_URL` secret
- [ ] Tests in `tests/test_event_bus.py`:
  - Test: publish → subscribe delivers the correct payload
  - Test: acknowledged events are not redelivered
  - Test: fallback mode (no Redis) works correctly with asyncio.Queue
  - Test: `get_pending_count` returns correct count after publishing 5 events

#### Acceptance Criteria
- [ ] `pytest tests/test_event_bus.py` passes (in both Redis and fallback modes)
- [ ] No `asyncio.Queue` imports remain in non-test production code
- [ ] `docker-compose up` starts Redis alongside the API without errors

---

## PHASE 2 — SYNTHETIC DATA REALISM
> **Goal:** Fix all 5 synthetic data quality issues from §10. All tasks are independent and can run in parallel. Requires Phase 0 TASK-006 output.

---

### TASK-201: Implement diurnal and seasonal temporal patterns in KPI generation
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 2  
**Original Ref:** T-020  
**Depends On:** TASK-006, TASK-103  
**Parallel With:** TASK-202, TASK-203, TASK-204, TASK-205  

#### Context
§10 Issue: "KPI time-series generated via AR(1) state machines — Real network KPIs have diurnal patterns, seasonal effects, and event-driven spikes that AR(1) may underrepresent."

Real telco network traffic follows well-understood patterns:
- **Diurnal**: Low traffic 2–6 AM, morning ramp 6–9 AM, business peak 9 AM–6 PM, evening entertainment peak 7–10 PM, night decline
- **Day-of-week**: Weekdays ~30% higher than weekends for enterprise traffic; weekends higher for residential
- **Seasonal**: Ramadan in Indonesia (major subscriber base) causes a significant shift — night traffic spikes, morning traffic drops, overall volume +15–20%
- **Event spikes**: Stadium cells during matches, transport hub cells during holidays

The generator should produce KPI series using an **additive decomposition model**: `KPI(t) = trend(t) + seasonal(t) + cyclical(t) + AR_residual(t)`

#### Deliverables
- [ ] New module `generators/temporal_model.py` with:
  - `DiurnalProfile` dataclass: 24-float array of hourly multipliers (must sum to 24.0 for energy conservation)
  - `CELL_TYPE_PROFILES: dict[str, DiurnalProfile]` — profiles for: `residential`, `enterprise`, `transport_hub`, `stadium`, `mixed`
  - `DayOfWeekProfile` dataclass: 7-float array
  - `SeasonalCalendar` class: given a date range, returns a seasonal multiplier per day (includes Indonesian public holidays and Ramadan detection via `hijri-converter` package)
  - `generate_kpi_series(base_value: float, start_date: datetime, hours: int, cell_type: str, add_ar_residual: bool = True) -> np.ndarray` — full additive model
- [ ] Updated generator to use `temporal_model` instead of bare AR(1)
- [ ] Tests in `tests/test_temporal_model.py`:
  - Test: Traffic between 2 AM and 5 AM < traffic between 9 AM and 11 AM for residential profile (at least 40% lower)
  - Test: Weekend traffic < weekday traffic for enterprise profile
  - Test: Generated series has autocorrelation structure (Ljung-Box test: AR residuals are white noise)
  - Test: Ramadan period has shifted diurnal pattern vs non-Ramadan

#### Acceptance Criteria
- [ ] `pytest tests/test_temporal_model.py` passes
- [ ] Visual inspection of 30-day generated series shows clear day/night pattern (validate by plotting with matplotlib and saving to `audit/temporal_pattern_sample.png`)
- [ ] AR(1) residuals have ADF test statistic < -3.0 (stationary)

---

### TASK-202: Implement configurable propagation delay profiles for cascading alarms
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 2  
**Original Ref:** T-021  
**Depends On:** TASK-006, TASK-103  
**Parallel With:** TASK-201, TASK-203, TASK-204, TASK-205  

#### Context
§10 Issue: "Alarm correlation chains — Synthetic cross-domain cascades may oversimplify real propagation delays. Model may expect instantaneous cascading when real propagation has variable latency."

In real networks, a failure at the transport layer takes time to propagate to the RAN layer because:
1. Element managers have polling intervals (typically 5–15 minutes)
2. Threshold crossing alerts have hysteresis delays (typically 2–5 minutes)
3. Cross-domain alarm correlation engines have processing latency (typically 1–3 minutes)
4. Some failures cause gradual degradation rather than hard failure

**Domain propagation delay ranges (from published post-incident reports):**
- RAN → Core: 8–25 minutes (varies by fault type)
- Transport → RAN: 3–15 minutes
- Core → BSS: 15–45 minutes (BSS polling is slower)
- Within-domain: 2–8 minutes

#### Deliverables
- [ ] New module `generators/cascade_model.py` with:
  - `PropagationProfile` dataclass: `source_domain: str, target_domain: str, min_delay_minutes: float, max_delay_minutes: float, delay_distribution: Literal['uniform', 'lognormal', 'exponential']`
  - `STANDARD_PROFILES: dict` — pre-defined profiles for all cross-domain pairs above
  - `CascadeInjector` class:
    - `inject_cascade(root_fault: FaultEvent, topology: NetworkTopology, profile: PropagationProfile) -> list[FaultEvent]` — returns list of downstream fault events with stochastic delays sampled from the profile distribution
    - `get_alarm_sequence(cascade: list[FaultEvent]) -> list[tuple[datetime, str, str]]` — returns sorted alarm sequence
- [ ] Updated fault injection in the generator to use `CascadeInjector`
- [ ] Tests in `tests/test_cascade_model.py`:
  - Test: A RAN fault always generates a downstream Core alarm with delay in [8, 25] minutes
  - Test: Alarm sequence is correctly time-ordered
  - Test: Lognormal delays produce correct distribution shape (mean, std in expected range)

#### Acceptance Criteria
- [ ] `pytest tests/test_cascade_model.py` passes
- [ ] In generated `events_alarms.parquet`, cross-domain alarm pairs have temporal gaps matching profile ranges (validate with a data quality check script)

---

### TASK-203: Calibrate CMDB degradation rates against realistic patterns
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 2  
**Original Ref:** T-022  
**Depends On:** TASK-006, TASK-103  
**Parallel With:** TASK-201, TASK-202, TASK-204, TASK-205  

#### Context
§10 Issue: "CMDB degradation patterns — Synthetic divergence may not reflect actual CMDB decay rates."

Published research on CMDB accuracy in large enterprises suggests:
- CMDB records degrade at approximately 3–7% per quarter for hardware CIs (decommission without removal)
- 8–15% of CI relationships become phantom within 12 months of a major network change
- Identity mutations (hardware swaps) affect approximately 2–4% of CIs per year in active 5G networks
- Dark nodes accumulate at approximately 5–10% per major software release cycle (elastic VNFs not registered)

The synthetic generator must parametrise these rates rather than using arbitrary values.

#### Deliverables
- [ ] New module `generators/cmdb_decay_model.py` with:
  - `CMDBDecayConfig` dataclass: `phantom_ci_rate_quarterly: float = 0.05`, `phantom_edge_rate_annual: float = 0.11`, `identity_mutation_rate_annual: float = 0.03`, `dark_node_rate_per_release: float = 0.07`, `dark_edge_rate_annual: float = 0.08`
  - `REALISTIC_DECAY_CONFIG: CMDBDecayConfig` — uses the calibrated values above
  - `ACCELERATED_DECAY_CONFIG: CMDBDecayConfig` — 2× for testing Dark Graph detection sensitivity
  - `apply_decay(cmdb_snapshot: pd.DataFrame, config: CMDBDecayConfig, simulation_months: int) -> tuple[pd.DataFrame, pd.DataFrame]` — returns (degraded_cmdb, divergence_ground_truth)
- [ ] Environment variable `CMDB_DECAY_PROFILE` (values: `realistic`, `accelerated`, default: `realistic`)
- [ ] Updated generator to use `CMDBDecayConfig`
- [ ] `divergence_ground_truth` must be exported as `divergence_manifest.parquet` with columns: `entity_id, divergence_type, injected_at_month, expected_detection_score`
- [ ] Tests in `tests/test_cmdb_decay.py`:
  - Test: After 12 months with realistic config, between 3–7% of CIs are phantom
  - Test: `divergence_manifest.parquet` is not empty after decay application
  - Test: accelerated config produces ~2× divergence rate vs realistic config

#### Acceptance Criteria
- [ ] `pytest tests/test_cmdb_decay.py` passes
- [ ] `divergence_manifest.parquet` exists and has schema: `entity_id (str), divergence_type (str), injected_at_month (int), expected_detection_score (float)`

---

### TASK-204: Validate synthetic fault scenarios against published post-incident patterns
**Project:** Sleeping-Cell-KPI-Data  
**Phase:** 2  
**Original Ref:** T-019  
**Depends On:** TASK-006, TASK-103  
**Parallel With:** TASK-201, TASK-202, TASK-203, TASK-205  

#### Context
§10 Issue: "Scenario realism — Injected faults may not reflect real-world failure patterns. Model learns synthetic failure modes that don't occur in production."

This task creates a **scenario validation framework** that compares generated fault characteristics against a reference library of real-world fault patterns derived from publicly available post-incident reports (Vodafone UK 2023 outage, O2 UK 2018 outage, T-Mobile US 2020 outage — all publicly published root cause analyses).

**Key fault signatures to validate:**
1. **Sleeping cell**: Zero user count + healthy-looking KPIs — confirm generator produces this correctly
2. **Congestion cascade**: PRB utilisation > 90% → latency spike (non-linear) → call drops — confirm non-linearity
3. **Hardware swap (Identity Mutation)**: Serial number change + KPI continuity — confirm no KPI discontinuity at swap point
4. **Transport link failure**: Packet loss spike → RAN degradation (with propagation delay) — confirm delay is realistic

#### Deliverables
- [ ] New module `validators/scenario_validator.py` with:
  - `ScenarioSpec` dataclass: `name: str, required_kpi_signatures: list[KPISignature], forbidden_kpi_signatures: list[KPISignature]`
  - `KPISignature` dataclass: `kpi_name: str, condition: Literal['zero', 'spike', 'continuity', 'non_linear_above'], threshold: float`
  - `validate_scenario(scenario_name: str, kpi_data: pd.DataFrame, alarm_data: pd.DataFrame) -> ValidationResult` — returns pass/fail with detail
  - Pre-loaded specs for all 4 fault signatures above
- [ ] CLI script `validate_scenarios.py` that runs all validators against the generated Parquet files and prints a report
- [ ] Tests in `tests/test_scenario_validator.py`:
  - Test: sleeping cell scenario passes validation (zero user count confirmed)
  - Test: a deliberately corrupted scenario (sleeping cell with non-zero users) fails validation
  - Test: validator report is JSON-serialisable

#### Acceptance Criteria
- [ ] `python validate_scenarios.py` exits 0 with all scenarios PASS
- [ ] `pytest tests/test_scenario_validator.py` passes
- [ ] Validation report saved to `audit/scenario_validation_report.json`

---

### TASK-205: Implement Abeyance Memory cold storage retrieval pipeline
**Project:** Pedk.ai  
**Phase:** 2  
**Original Ref:** T-016  
**Depends On:** TASK-003, TASK-102  
**Parallel With:** TASK-201 through TASK-204  

#### Context
§4 Engineering Maturity: "Long-horizon retrieval (>30 days) — ⚠️ Partial. Cold storage retrieval pipeline incomplete."

The storage architecture (§9) defines three tiers:
- Hot: Redis / TimescaleDB, 24–48 hours
- Warm: PostgreSQL + pgvector, 30–90 days
- Cold: S3 / Parquet / Apache Iceberg, 1–7 years

Abeyance Memory fragments older than 90 days must be archived to cold storage but remain retrievable for similarity search. The challenge is that pgvector doesn't index cold storage — you need a retrieval strategy that searches warm storage first and falls back to cold storage only when warm similarity scores are below a threshold.

#### Deliverables
- [ ] `services/abeyance/cold_storage.py` with `AbeyanceColdStorage` class:
  - `archive_fragment(fragment: AbeyanceFragment) -> str` — serialises fragment (with embedding) to S3/local Parquet, returns archive path; uses `COLD_STORAGE_BACKEND` env var (`s3` or `local`, default `local` for dev)
  - `search_cold(query_embedding: np.ndarray, top_k: int = 5, tenant_id: UUID) -> list[AbeyanceFragment]` — loads Parquet, computes cosine similarity in-memory (Faiss flat index for batch), returns top-k
  - `cold_storage_path(tenant_id: UUID, year: int, month: int) -> str` — deterministic path scheme: `{base_path}/{tenant_id}/{year}/{month:02d}/fragments.parquet`
- [ ] Updated `AbeyanceMemoryService.search()` to implement waterfall: warm search first → if max warm score < `COLD_SEARCH_THRESHOLD` (default: `0.7`), extend search to cold storage → merge and re-rank results
- [ ] Scheduled archival job: fragments with `status='ACTIVE'` and `created_at < NOW() - WARM_RETENTION_DAYS (default 90)` are archived to cold and removed from warm
- [ ] Tests in `tests/test_cold_storage.py`:
  - Test: a fragment archived to local cold storage can be retrieved by similarity search
  - Test: waterfall search finds a fragment that only exists in cold storage
  - Test: cold storage path scheme is deterministic for same inputs
  - Test: archival job removes fragments from warm after archiving

#### Acceptance Criteria
- [ ] `pytest tests/test_cold_storage.py` passes (local backend)
- [ ] Round-trip: fragment → archive → retrieve by similarity returns fragment with cosine similarity > 0.99
- [ ] Warm + cold waterfall search latency < 500ms for 10,000 warm fragments + 100,000 cold fragments (benchmark in test)

---

## PHASE 3 — CORE ENGINE UPGRADES
> **Goal:** Implement the remaining intelligence engine features. Some tasks depend on Phase 2 outputs. Run in parallel where possible.

---

### TASK-301: Implement Dark Graph Divergence Report generation
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-025  
**Depends On:** TASK-002, TASK-203 (for ground truth schema)  
**Parallel With:** TASK-302, TASK-303, TASK-304  

#### Context
§6 Feature 1: "Divergence Report — 🔨 In Progress." This is Pedk.ai's most important deliverable — the product's entry wedge. Within 48 hours of receiving three read-only datasets (CMDB snapshot, telemetry time-series, ITSM ticket archive), Pedk.ai must produce a Divergence Report identifying all Dark Graph elements.

The report must cover all 6 divergence types from §2:
1. Dark Nodes — telemetry from entities with no CMDB record
2. Phantom Nodes — CMDB CIs with zero telemetry for > 90 days
3. Dark Edges — undocumented connections between entities
4. Phantom Edges — CMDB-declared connections with zero traffic
5. Dark Attributes — CIs with incorrect/missing properties
6. Identity Mutations — same logical function, different physical entity

#### Deliverables
- [ ] `services/dark_graph/divergence_reporter.py` with `DivergenceReporter` class:
  - `load_cmdb_snapshot(path: str) -> CMDBSnapshot` — reads CSV/JSON/Parquet CMDB export
  - `load_telemetry_series(path: str) -> TelemetrySeries` — reads historical PM counters
  - `load_ticket_archive(path: str) -> TicketArchive` — reads ITSM ticket export
  - `find_dark_nodes(cmdb: CMDBSnapshot, telemetry: TelemetrySeries) -> list[DivergenceFinding]`
  - `find_phantom_nodes(cmdb: CMDBSnapshot, telemetry: TelemetrySeries, threshold_days: int = 90) -> list[DivergenceFinding]`
  - `find_identity_mutations(cmdb: CMDBSnapshot, telemetry: TelemetrySeries) -> list[DivergenceFinding]`
  - `find_behavioural_dark_edges(tickets: TicketArchive, cmdb: CMDBSnapshot) -> list[DivergenceFinding]`
  - `generate_report(tenant_id: UUID) -> DivergenceReport` — calls all find_* methods, aggregates, computes confidence scores via `FusionMethodologyFactory`
- [ ] `DivergenceFinding` dataclass: `finding_type: str, entity_id: str, confidence: float, evidence: list[str], recommended_action: str`
- [ ] `DivergenceReport` dataclass: `tenant_id, generated_at, findings: list[DivergenceFinding], summary_stats: dict`
- [ ] POST `/api/v1/dark-graph/analyze` endpoint: accepts multipart upload of 3 files, triggers analysis, returns job ID
- [ ] GET `/api/v1/dark-graph/report/{job_id}` endpoint: returns report when ready
- [ ] Tests using synthetic data from Sleeping-Cell-KPI-Data (`cmdb_declared_entities.parquet` + KPI files + a mock ticket archive)

#### Acceptance Criteria
- [ ] With synthetic data including 100 injected divergences (from `divergence_manifest.parquet`): report finds ≥ 70 of them (70% recall)
- [ ] False positive rate < 10% (confirmed against ground truth)
- [ ] Report generates within 60 seconds for synthetic dataset size (811k entities)
- [ ] Report is JSON-serialisable and exports correctly

---

### TASK-302: Implement Datagerry CMDB sync adapter
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-025  
**Depends On:** TASK-002  
**Parallel With:** TASK-301, TASK-303, TASK-304  

#### Context
§6 Feature 1: "Datagerry CMDB sync adapter — 🔨 In Progress." Datagerry is an open-source CMDB used in the CasinoLimit dataset proof-of-concept. The adapter must periodically pull CMDB state into Pedk.ai's internal `NetworkEntityORM` and `EntityRelationshipORM` tables.

Datagerry exposes a REST API. The adapter must:
1. Poll Datagerry at a configurable interval (default: every 4 hours)
2. Fetch all CIs of relevant types (network elements)
3. Upsert into `NetworkEntityORM` (create new, update changed, mark missing as candidates for Phantom Node)
4. Track a sync cursor (last successful sync timestamp) to enable incremental sync

#### Deliverables
- [ ] `adapters/datagerry_adapter.py` with `DatagerryAdapter` class:
  - `__init__(base_url: str, api_token: str, tenant_id: UUID)`
  - `fetch_all_cis(ci_type: str = None) -> list[dict]` — calls `GET /rest/objects` with optional type filter
  - `fetch_ci_relationships() -> list[dict]` — calls `GET /rest/links`
  - `sync(since: datetime = None) -> SyncResult` — full or incremental sync, returns `{added: int, updated: int, unchanged: int, phantom_candidates: int}`
  - `upsert_entity(ci: dict, session: Session) -> NetworkEntityORM`
- [ ] Environment variables: `DATAGERRY_URL`, `DATAGERRY_API_TOKEN`
- [ ] Sync job registered in scheduler with `DATAGERRY_SYNC_INTERVAL_HOURS` (default: `4`)
- [ ] Tests using `responses` library to mock Datagerry HTTP responses:
  - Test: full sync creates expected entities in DB
  - Test: incremental sync only updates changed entities
  - Test: CI missing from Datagerry response is flagged as phantom candidate

#### Acceptance Criteria
- [ ] `pytest tests/test_datagerry_adapter.py` passes with mocked HTTP
- [ ] Sync result counts are correct for known mock data
- [ ] On HTTP 4xx/5xx, adapter logs error and does not crash

---

### TASK-303: Implement CasinoLimit telemetry parser
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-025  
**Depends On:** TASK-002  
**Parallel With:** TASK-301, TASK-302, TASK-304  

#### Context
§6 Feature 1: "CasinoLimit telemetry parser — 🔨 In Progress." The CasinoLimit dataset has three telemetry streams: network flows, syscalls, and MITRE ATT&CK labels. These streams are used as the proving ground for the Dark Graph engine — specifically for Type 1 divergences (Intrusion & Anomaly).

The parser must normalise these three streams into Pedk.ai's unified signal format (the same format used for Ericsson and Nokia signals from §11).

**CasinoLimit stream formats (from §10 context):**
- Network flows: `{src_ip, dst_ip, src_port, dst_port, protocol, bytes, packets, timestamp}`
- Syscalls: `{process_id, syscall_name, args, return_code, timestamp, host_id}`
- MITRE labels: `{timestamp, host_id, technique_id, tactic, confidence}`

#### Deliverables
- [ ] `adapters/casinolimit_parser.py` with `CasinoLimitParser` class:
  - `parse_network_flows(filepath: str) -> list[UnifiedSignal]`
  - `parse_syscalls(filepath: str) -> list[UnifiedSignal]`
  - `parse_mitre_labels(filepath: str) -> list[UnifiedSignal]`
  - `enrich_with_cmdb(signals: list[UnifiedSignal], cmdb: CMDBSnapshot) -> list[EnrichedSignal]` — cross-references IP/host IDs to CMDB entities, marking unmatched signals as potential Dark Node evidence
- [ ] `UnifiedSignal` dataclass: `entity_id: str | None, signal_type: str, timestamp: datetime, payload: dict, source: str, is_dark: bool`
- [ ] Tests using sample CasinoLimit data (create a minimal fixture with 100 records each):
  - Test: Network flow from unknown IP produces signal with `is_dark=True`
  - Test: Syscall from known host maps to correct `entity_id`
  - Test: MITRE label correctly annotates the enriched signal

#### Acceptance Criteria
- [ ] `pytest tests/test_casinolimit_parser.py` passes
- [ ] Parser handles malformed records without crashing (skips with warning log)
- [ ] 100% of MITRE-labelled signals result in a `DivergenceFinding` of type `INTRUSION_CANDIDATE`

---

### TASK-304: Implement Topological Ghost Masks
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-025  
**Depends On:** TASK-002  
**Parallel With:** TASK-301, TASK-302, TASK-303  

#### Context
§6 Feature 1: "Topological Ghost Masks — 🔨 In Progress." During planned maintenance, elements generate degraded KPIs and alarms that are expected — not anomalous. Without suppression, Pedk.ai would generate false positive SITREPs during every maintenance window, eroding operator trust.

Ghost Masks work by cross-referencing the ITSM change ticket schedule (change records with a planned start/end time and a list of affected CIs) against the anomaly detector's findings. Any anomaly finding whose affected entity has an active change record covering that time window is suppressed (masked) and labelled `GHOST_MASKED`.

#### Deliverables
- [ ] `services/ghost_mask.py` with `GhostMaskService` class:
  - `load_change_schedule(tickets: TicketArchive) -> list[ChangeWindow]` — parses change tickets with `change_type='planned_maintenance'`
  - `is_masked(entity_id: str, timestamp: datetime) -> bool` — returns True if entity has active change window
  - `apply_mask(findings: list[AnomalyFinding]) -> list[AnomalyFinding]` — sets `status='GHOST_MASKED'` on affected findings
  - `get_active_windows(timestamp: datetime) -> list[ChangeWindow]` — returns all currently active windows
- [ ] `ChangeWindow` dataclass: `ticket_id: str, affected_entity_ids: list[str], start_time: datetime, end_time: datetime, change_type: str`
- [ ] Ghost mask state cached in Redis (key: `ghost_mask:{tenant_id}:{entity_id}`, TTL: until window end)
- [ ] Ghost masked findings are **not deleted** — they are retained with `status='GHOST_MASKED'` for audit and are re-evaluated when the change window closes
- [ ] Tests in `tests/test_ghost_mask.py`:
  - Test: entity with active change window has findings masked
  - Test: entity without change window is unaffected
  - Test: masking expires when change window ends (mock time)
  - Test: masked findings are retained (not deleted) in database

#### Acceptance Criteria
- [ ] `pytest tests/test_ghost_mask.py` passes
- [ ] Running anomaly detection during a synthetic maintenance window produces zero non-masked findings for the affected entity
- [ ] Audit log contains all masked findings with `reason='GHOST_MASKED'` and the associated change ticket ID

---

### TASK-305: Implement PCMCI causal graph discovery
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-023  
**Depends On:** TASK-106  
**Parallel With:** None (serial after TASK-106)  

#### Context
§8 recommends PCMCI (Peter Clark – Momentary Conditional Independence) as the V2 upgrade for full **causal graph discovery** (not just pairwise causation like Granger and Transfer Entropy). PCMCI discovers the full directed acyclic graph of causal relationships across all KPI metrics simultaneously, controlling for confounders.

PCMCI from the `tigramite` Python package is the reference implementation. The adapter must wrap `tigramite.pcmci.PCMCI` to implement the `CausalInferenceMethod` interface from TASK-106.

The key difference: Granger and TE operate pairwise (X→Y). PCMCI operates over a full multivariate time series (all KPIs simultaneously) and returns a `CausalGraph` — a dict mapping `(source_metric, target_metric, lag)` to `(coefficient, p_value)`.

#### Deliverables
- [ ] `services/causal/pcmci_method.py` implementing `CausalInferenceMethod` interface:
  - `compute_graph(data: np.ndarray, var_names: list[str], max_lag: int = 6) -> CausalGraph` — wraps `tigramite.pcmci.PCMCI`
  - `compute(x: np.ndarray, y: np.ndarray, lag: int) -> CausalResult` — interface compliance; internally calls `compute_graph` and extracts the X→Y edge
  - Conditional independence test: `ParCorr` (linear) by default, `CMIknn` (non-linear) when `PCMCI_NONLINEAR=true`
  - `alpha_level` configurable via `PCMCI_ALPHA` env var (default: `0.05`)
- [ ] `CausalGraph` dataclass: `edges: dict[tuple[str,str,int], tuple[float,float]]`, `summary() -> str`
- [ ] `CAUSAL_METHOD=pcmci` registered in `CausalMethodFactory`
- [ ] Tests in `tests/test_pcmci.py`:
  - Test: 3-variable system where X→Z and Y→Z (with no X→Y) produces correct graph
  - Test: spurious correlation between X and Y (both caused by hidden Z) is correctly identified as non-causal when Z is included
  - Test: `compute()` interface compatibility with factory

#### Acceptance Criteria
- [ ] `pytest tests/test_pcmci.py` passes
- [ ] For known 3-variable system: correct edges detected, spurious edge rejected
- [ ] `tigramite` added to `requirements.txt`

---

### TASK-306: Implement Abeyance Memory multi-modal matching
**Project:** Pedk.ai  
**Phase:** 3  
**Original Ref:** T-026  
**Depends On:** TASK-003, TASK-102, TASK-205  
**Parallel With:** TASK-301 through TASK-305  

#### Context
§4 Engineering Maturity: "Multi-modal matching (text + telemetry) — ⚠️ Partial. Need structured telemetry-to-text alignment."

Currently, the Abeyance Memory stores text fragments (from ticket notes) and finds similar text via pgvector cosine similarity. The missing piece is **bridging structured telemetry data into the same semantic space** so a telemetry anomaly can "snap" to a historical text fragment.

The alignment strategy: convert structured telemetry anomaly events into a **natural language description** (a text summary), then embed that summary using the same embedding model used for text fragments. This allows similarity search to work across both modalities.

**Telemetry-to-text template:**
```
"On {timestamp}, cell {entity_id} in {domain} showed {kpi_name} at {value} ({z_score:.1f} standard deviations from baseline). 
Affected metrics: {affected_metrics_list}. Similar to {neighbour_count} neighbours: {neighbour_summary}."
```

#### Deliverables
- [ ] `services/abeyance/telemetry_aligner.py` with `TelemetryAligner` class:
  - `anomaly_to_text(anomaly: AnomalyFinding) -> str` — generates natural language description from anomaly event
  - `embed_anomaly(anomaly: AnomalyFinding) -> np.ndarray` — converts anomaly to embedding via LLMService
  - `store_anomaly_fragment(anomaly: AnomalyFinding, tenant_id: UUID) -> AbeyanceFragment` — stores in Abeyance Memory with `modality='telemetry'`
- [ ] Updated `AbeyanceMemoryService.snap()` to work across modalities:
  - When searching for snaps, searches both `modality='text'` and `modality='telemetry'` fragments
  - Cross-modal snaps (text↔telemetry) are labelled `snap_type='cross_modal'` in the hypothesis record
- [ ] Tests in `tests/test_multimodal_abeyance.py`:
  - Test: an anomaly event stored as telemetry fragment can be found by a text query describing similar conditions
  - Test: a text fragment from a ticket can snap with a telemetry anomaly on the same entity
  - Test: cross-modal snap produces `snap_type='cross_modal'` in the hypothesis

#### Acceptance Criteria
- [ ] `pytest tests/test_multimodal_abeyance.py` passes
- [ ] Cross-modal snap occurs at similarity > 0.85 for semantically equivalent text and telemetry descriptions
- [ ] `modality` column added to Abeyance Memory table via Alembic migration

---

## PHASE 4 — OPERATOR EXPERIENCE & FEEDBACK
> **Goal:** Build the operator-facing feedback loop — the highest-value learning signal. Some tasks are serial.

---

### TASK-401: Implement behavioural observation feedback pipeline
**Project:** Pedk.ai  
**Phase:** 4  
**Original Ref:** T-003  
**Depends On:** TASK-004, TASK-107  
**Parallel With:** TASK-402, TASK-403  

#### Context
§7 Engineering Maturity: "Behavioural observation pipeline — ❌ Not implemented. Critical gap — highest value signal channel."

This is the most important feedback signal. When Pedk.ai generates a SITREP recommending action X, and the operator actually does action Y, the delta (X≠Y) is the learning signal. This requires:
1. Recording exactly what Pedk.ai recommended (already stored in `DecisionTraceORM`)
2. Ingesting operator actions from the ITSM system (what they actually did)
3. Computing the delta and routing it as a feedback event to the event bus

The ITSM integration is ServiceNow-first (most common at Tier-1 operators). Use ServiceNow's Table API: `GET /api/now/table/incident` with a filter on `sys_updated_on` since last poll.

#### Deliverables
- [ ] `adapters/servicenow_observer.py` with `ServiceNowObserver` class:
  - `poll_recent_actions(since: datetime, tenant_id: UUID) -> list[OperatorAction]` — polls ServiceNow for tickets updated since last poll
  - `correlate_with_recommendation(action: OperatorAction, tenant_id: UUID) -> FeedbackDelta | None` — matches ITSM action to a Pedk.ai recommendation via `external_correlation_id`
  - `extract_resolution_code(ticket: dict) -> str` — maps ServiceNow close codes to Pedk.ai action categories
- [ ] `OperatorAction` dataclass: `ticket_id, correlation_id, operator_id, timestamp, action_type, resolution_code, modified_fields: dict`
- [ ] `FeedbackDelta` dataclass: `recommendation_id, operator_action: OperatorAction, agreement_score: float, divergence_fields: list[str]`
  - `agreement_score = 1.0` if operator followed recommendation exactly; `0.5` if partially; `0.0` if contradicted
- [ ] Published as `operator.feedback_received` event on event bus (TASK-107)
- [ ] Polling job: `SERVICENOW_POLL_INTERVAL_MINUTES` (default: `10`)
- [ ] Tests using `responses` library for ServiceNow HTTP mocks:
  - Test: ticket with matching `external_correlation_id` produces `FeedbackDelta`
  - Test: agreement score is 1.0 when operator action matches recommendation
  - Test: agreement score is 0.0 when operator contradicts recommendation

#### Acceptance Criteria
- [ ] `pytest tests/test_servicenow_observer.py` passes
- [ ] `FeedbackDelta` events appear in event bus after polling
- [ ] Missing `SERVICENOW_URL` or `SERVICENOW_TOKEN` env vars: adapter logs warning and skips poll (does not crash)

---

### TASK-402: Implement structured multi-dimensional operator assessment
**Project:** Pedk.ai  
**Phase:** 4  
**Original Ref:** T-007  
**Depends On:** TASK-004  
**Parallel With:** TASK-401, TASK-403  

#### Context
§7: "Structured Assessment — ❌ Not implemented." The multi-dimensional assessment allows operators to rate Pedk.ai's SITREPs on three dimensions: accuracy (1–5), relevance (1–5), actionability (1–5), plus optional freeform text.

This is a higher-signal-quality mechanism than thumbs up/down (which is already implemented) and lower-signal-quality than behavioural observation (TASK-401). Together, the three channels form the complete feedback loop described in §7.

#### Deliverables
- [ ] New Pydantic schema `StructuredFeedback`: `decision_id: UUID, operator_id: UUID, accuracy_score: int (1-5), relevance_score: int (1-5), actionability_score: int (1-5), freeform_notes: str | None, dimension_explanations: dict[str, str] | None`
- [ ] POST `/api/v1/feedback/structured` endpoint — stores structured feedback, validates score ranges
- [ ] GET `/api/v1/feedback/summary/{decision_id}` endpoint — returns aggregate scores across all operators for a decision (mean, std dev per dimension, response count)
- [ ] Updated `DecisionFeedbackORM` to add columns: `accuracy_score`, `relevance_score`, `actionability_score`, `freeform_notes` (all nullable for backward compatibility with existing binary feedback)
- [ ] Alembic migration for schema change
- [ ] Anti-gaming safeguard: one structured feedback per operator per decision (unique constraint on `(decision_id, operator_id)`)
- [ ] Tests in `tests/test_structured_feedback.py`:
  - Test: valid structured feedback is accepted and stored
  - Test: score out of range (e.g., `accuracy_score = 6`) returns 422
  - Test: duplicate feedback from same operator returns 409
  - Test: summary endpoint returns correct mean/std

#### Acceptance Criteria
- [ ] `pytest tests/test_structured_feedback.py` passes
- [ ] Migration runs cleanly against existing database with binary feedback records (no data loss)
- [ ] GET summary returns `null` for dimensions not yet rated (not 0)

---

### TASK-403: Implement continuous evaluation pipeline
**Project:** Pedk.ai  
**Phase:** 4  
**Original Ref:** T-005  
**Depends On:** TASK-301 (for divergence report scoring), TASK-401 (for feedback events)  
**Parallel With:** TASK-401, TASK-402  

#### Context
§14 Lens 1 Evaluation score: 3/5. "Decision memory benchmark (0.9 threshold). Causal AI validated. Need continuous evaluation pipeline."

The evaluation pipeline must track Pedk.ai's performance over time across three business-linked metrics (from §1):
1. **CMDB accuracy improvement** — `% reduction in divergence findings vs baseline`
2. **MTTR correlation** — `correlation coefficient between Pedk.ai SITREP usage and ticket resolution time`
3. **Undocumented dependency discovery rate** — `new Dark Edges discovered per week`

These metrics must be computed automatically on a rolling 7-day window and written to a `ModelPerformanceORM` table.

#### Deliverables
- [ ] `ModelPerformanceORM` table: `tenant_id, metric_name, metric_value, window_start, window_end, computed_at`
- [ ] `services/evaluation_pipeline.py` with `EvaluationPipeline` class:
  - `compute_cmdb_accuracy(tenant_id: UUID, window_days: int = 7) -> float` — queries divergence report history
  - `compute_mttr_correlation(tenant_id: UUID, window_days: int = 7) -> float` — joins `DecisionTraceORM` with ITSM resolution times (from ServiceNow observer or ticket archive)
  - `compute_discovery_rate(tenant_id: UUID, window_days: int = 7) -> float` — counts new Dark Edge findings per day
  - `run_evaluation(tenant_id: UUID) -> dict[str, float]` — runs all three, persists to `ModelPerformanceORM`
- [ ] Evaluation job scheduled daily at 02:00 UTC (`EVAL_SCHEDULE_CRON` env var)
- [ ] GET `/api/v1/evaluation/metrics/{tenant_id}` endpoint returns last 30 days of metrics
- [ ] Tests in `tests/test_evaluation_pipeline.py`:
  - Test: metrics are computed correctly from known fixture data
  - Test: metrics are written to `ModelPerformanceORM`
  - Test: endpoint returns correct shape and values

#### Acceptance Criteria
- [ ] `pytest tests/test_evaluation_pipeline.py` passes
- [ ] Evaluation pipeline runs without error on synthetic dataset
- [ ] Metrics endpoint is accessible and returns data within 200ms (cached)

---

### TASK-404: Frontend decomposition — split monolithic page.tsx
**Project:** Pedk.ai  
**Phase:** 4  
**Original Ref:** T-027  
**Depends On:** TASK-007  
**Parallel With:** TASK-401, TASK-402, TASK-403  

#### Context
§17 task T-027: "Frontend decomposition: split monolithic `page.tsx` into routed pages." The audit in TASK-007 identified the current component list and line count. A Next.js App Router structure with separate route segments is the target state.

**Target routing structure:**
```
app/
  layout.tsx           — shared nav, auth wrapper
  page.tsx             — dashboard home (summary widgets only)
  dark-graph/
    page.tsx           — Dark Graph visualisation and divergence report
  anomalies/
    page.tsx           — anomaly detection feed
  sleeping-cells/
    page.tsx           — sleeping cell detection dashboard
  capacity/
    page.tsx           — capacity planning
  feedback/
    page.tsx           — operator feedback interface
  settings/
    page.tsx           — tenant configuration
```

#### Deliverables
- [ ] New routing structure created per the target above
- [ ] All components extracted from monolithic `page.tsx` into their correct route `page.tsx`
- [ ] Shared components that appear in multiple pages moved to `components/` directory
- [ ] Navigation component in `layout.tsx` with links to all routes
- [ ] No functionality removed — all existing API calls preserved in the correct route page
- [ ] No new dependencies added — use only what is already in `package.json`
- [ ] Tests (Playwright or React Testing Library — use whichever is already in the project):
  - Test: root `/` page renders without error
  - Test: `/dark-graph` page renders without error
  - Test: `/anomalies` page renders without error
  - Test: navigation links are present on all pages

#### Acceptance Criteria
- [ ] `npm run build` exits 0 with no TypeScript errors
- [ ] All original API call endpoints are preserved (grep confirms no API paths were removed)
- [ ] Original `page.tsx` line count reduced by > 80%

---

### TASK-405: Expand test suite — safety gate coverage
**Project:** Pedk.ai  
**Phase:** 4  
**Original Ref:** T-028  
**Depends On:** TASK-008 (audit)  
**Parallel With:** TASK-401 through TASK-404  

#### Context
§17 task T-028: "Phase 5 test suite: expand from ~5 trivial tests to comprehensive safety gate coverage." §3 Layer 5 describes 7 safety gates for autonomous actions. The audit in TASK-008 identified the safety gate code locations.

The 7 safety gates (from the spec architecture — §3 Layer 5):
1. Explainability gate — no action without reasoning trace
2. Scope gate — action must be within operator-approved action types
3. Risk threshold gate — action risk score must be below configured threshold
4. Maintenance window gate — no autonomous action during active change window
5. Duplicate action gate — prevents re-executing the same action within a cooldown period
6. Rollback availability gate — action must have a defined rollback procedure
7. Human approval gate — at Level 3 autonomy, operator approval recorded

#### Deliverables
- [ ] `tests/test_safety_gates.py` with at minimum 3 tests per gate (21 total):
  - For each gate: test passes when condition is met, test fails (raises `SafetyGateViolation`) when condition is violated, test edge case (e.g., boundary value)
- [ ] `tests/test_action_execution.py` — integration tests for the full action execution pipeline:
  - Test: action that passes all 7 gates is executed
  - Test: action that fails gate 1 (no explainability) is rejected with correct error code
  - Test: action that fails gate 4 (maintenance window active) is rejected and logged
  - Test: kill-switch disables all autonomous actions immediately
- [ ] All tests use fixtures — no live database, no live network calls

#### Acceptance Criteria
- [ ] `pytest tests/test_safety_gates.py tests/test_action_execution.py` passes with 0 failures
- [ ] Total test count in entire test suite increases by at least 30 from the baseline (documented in audit TASK-008)
- [ ] Test coverage report (`pytest --cov`) shows > 70% coverage on safety gate module

---

## PHASE 5 — GOVERNANCE, COMPLIANCE & DOCUMENTATION
> **Goal:** Write all regulatory and governance documents. All tasks are independent and can run in parallel. These are documentation tasks, not code tasks. Output is well-structured, professional prose.

---

### TASK-501: Write OFCOM pre-notification document
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-006  
**Depends On:** Nothing (but benefits from having TASK-301 complete for architecture accuracy)  
**Parallel With:** TASK-502, TASK-503, TASK-504  

#### Context
§13 Regulatory Compliance: "OFCOM — Pre-notification document — ❌ Stub — Substantive rewrite required — must cover architecture, risk analysis, vendor compatibility."

Pedk.ai operates in the UK telecoms sector, processing operational data from OFCOM-regulated operators. OFCOM's regulatory framework requires that AI systems affecting network operations be documented for pre-notification. This document is NOT a legal filing — it is a preparatory document that an operator's regulatory team would use when notifying OFCOM.

This document must be written as if authored by Pedk.ai's regulatory compliance team and addressed to the operator's Head of Regulatory Affairs.

#### Deliverables
- [ ] `docs/regulatory/OFCOM_PRE_NOTIFICATION.md` with these sections:
  1. **Executive Summary** (~300 words): What Pedk.ai is, what it touches, what it does not touch
  2. **System Architecture** (~500 words): The 5-layer architecture, data flows, what data is processed, where it is stored, data residency
  3. **Autonomy Level Declaration** (~300 words): Current deployment is advisory-only (Level 0); progression to Level 3 requires operator consent; the autonomy spectrum table from §7
  4. **Risk Analysis** (~500 words): Failure modes, impact on network availability, safeguards, the 7 safety gates
  5. **Vendor Compatibility Statement** (~200 words): Ericsson/Nokia compatibility, TMF API compliance, no interference with element managers
  6. **Data Protection Summary** (~300 words): What data is NOT accessed (no subscriber PII, no billing, no revenue data in Day 1 deployment), GDPR references, encryption at rest and in transit
  7. **Incident Response Protocol** (~200 words): Kill-switch, human override, escalation path
- [ ] Total length: 2,300–3,000 words. Professional regulatory tone. No marketing language.

#### Acceptance Criteria
- [ ] Document exists at correct path
- [ ] All 7 sections present and within word count guidance
- [ ] Does not contradict the product spec (no claims of capabilities not in the spec)
- [ ] Does not claim regulatory approval (this is a pre-notification, not an approval)

---

### TASK-502: Write ICO Data Protection Impact Assessment (DPIA)
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-006  
**Depends On:** Nothing  
**Parallel With:** TASK-501, TASK-503, TASK-504  

#### Context
§13: "ICO — Data Protection Impact Assessment — ❌ Stub — Full DPIA covering data flows, retention periods, consent mechanisms, international transfers."

Under UK GDPR, a DPIA is required for processing that is likely to result in a high risk to individuals. While Pedk.ai's Day 1 deployment doesn't process subscriber PII, the BSS integration roadmap (§13) will eventually touch customer data. The DPIA must cover both current state and the roadmap state.

ICO's DPIA template structure must be followed (publicly available on ico.org.uk).

#### Deliverables
- [ ] `docs/regulatory/ICO_DPIA.md` covering:
  1. **Description of Processing**: What data is processed, by whom, for what purpose, on what legal basis
  2. **Necessity and Proportionality Assessment**: Why this data processing is necessary; less privacy-invasive alternatives considered
  3. **Data Flow Diagram** (described in text/ASCII since this is markdown): Source → Pedk.ai → Storage → LLM provider → Operator output
  4. **Risk Identification**: Table of risks to data subjects (operators' employees, subscribers)
  5. **Risk Mitigation Measures**: Technical and organisational measures per risk
  6. **Retention Periods**: Per data category (telemetry, CMDB, tickets, decision traces)
  7. **International Transfers**: LLM API calls to cloud providers (where data goes, what safeguards apply)
  8. **Consultation**: Who was consulted in preparing this DPIA
  9. **Sign-off Section**: Roles and responsibilities placeholder
- [ ] Total length: 2,000–3,000 words.

#### Acceptance Criteria
- [ ] All 9 ICO DPIA sections present
- [ ] International transfers section explicitly addresses LLM API calls (data sent to Gemini/GPT/Claude)
- [ ] Retention periods are consistent with §9 storage architecture table (Hot: 24–48h, Warm: 30–90 days, Cold: 1–7 years)

---

### TASK-503: Write Autonomous Safety Whitepaper
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-006  
**Depends On:** Nothing  
**Parallel With:** TASK-501, TASK-502, TASK-504  

#### Context
§13: "Safety — Autonomous Safety Whitepaper — ❌ Stub — Architecture safety analysis, failure modes, testing methodology, rollback procedures."

This whitepaper is the technical safety case for Pedk.ai's autonomous capabilities. It must demonstrate that the system cannot cause harm that exceeds the defined risk thresholds, even in failure modes.

Target audience: operator CTO, CISO, and their safety review boards.

#### Deliverables
- [ ] `docs/regulatory/AUTONOMOUS_SAFETY_WHITEPAPER.md` with sections:
  1. **Safety Philosophy** (~300 words): Advisory-first; autonomy as a spectrum; operator always in control
  2. **Threat Model** (~600 words): Table of failure modes — for each: `failure_mode, probability, impact, detection_method, mitigation`; cover at minimum: false positive SITREP, false negative (missed critical fault), autonomous action on wrong entity, autonomous action during maintenance window, LLM hallucination in SITREP
  3. **The 7 Safety Gates** (~500 words): Each gate described with its technical implementation and the failure mode it prevents
  4. **Kill-Switch Architecture** (~300 words): How the kill-switch works, who can invoke it, what state is preserved
  5. **Testing Methodology** (~400 words): How safety gates are tested, the synthetic fault injection approach, chaos engineering principles
  6. **Rollback Procedures** (~300 words): Per action type, what rollback means and how it is executed
  7. **Incident Reporting** (~200 words): Post-autonomous-action incident classification and reporting obligations
- [ ] Total length: 2,600–3,500 words.

#### Acceptance Criteria
- [ ] All 7 sections present
- [ ] Threat model table has ≥ 8 failure modes
- [ ] Each of the 7 safety gates is described individually
- [ ] Kill-switch invocation procedure is unambiguous

---

### TASK-504: Write AI Behaviour Specification per Autonomy Level
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-002  
**Depends On:** Nothing  
**Parallel With:** TASK-501, TASK-502, TASK-503  

#### Context
§14 Lens 1: "T-002: Formalise behaviour specification per autonomy level." §7 defines 4 autonomy levels (0–3). Each level needs a precise specification of what Pedk.ai does, what it does not do, and the exact conditions for level transitions.

This document is used by: (a) NOC engineers during onboarding to understand what Pedk.ai will do at their current level, (b) the engineering team to implement guardrails correctly, (c) the safety review process to validate that the implementation matches the specification.

#### Deliverables
- [ ] `docs/AI_BEHAVIOUR_SPEC.md` with:
  1. **Level 0 — Advisory Only**: Complete list of actions Pedk.ai takes (generates SITREP, logs decision trace, updates Abeyance Memory, computes decay scores); complete list of actions it does NOT take (no ITSM writes, no config changes, no alarm acknowledgements); output format specification for SITREPs
  2. **Level 1 — Assisted**: Additional actions enabled vs Level 0 (draft ticket creation, pre-populated fields); required operator interaction before any write action; draft ticket field specifications
  3. **Level 2 — Supervised**: Actions executable autonomously with operator override window; override window duration (configurable, default: 30 minutes); what happens if no operator response (action proceeds); logging requirements
  4. **Level 3 — Gated Autonomous**: Full autonomous action types permitted; all 7 safety gates enforced; audit trail requirements; kill-switch specification
  5. **Level Transition Criteria**: Prerequisites for each level transition (not just technical, but trust criteria — "at least 90 days of Level N-1 with < 5% false positive rate")
  6. **Forbidden Actions at All Levels**: Exhaustive list — actions Pedk.ai will never take regardless of autonomy level (e.g., modify billing records, access subscriber PII, disable emergency services routing)
- [ ] Total length: 2,000–2,500 words.

#### Acceptance Criteria
- [ ] All 6 sections present
- [ ] Level 0 forbidden actions list has ≥ 10 items
- [ ] Level transition criteria are measurable (not vague — each criterion has a threshold)

---

### TASK-505: Write NOC Engineer Role Specification
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-011  
**Depends On:** Nothing  
**Parallel With:** TASK-501 through TASK-504  

#### Context
§14 Lens 3 Skills: "T-011: Define AI-adjusted NOC engineer role specification." The Erdos methodology requires explicit role redesign when introducing AI into a workflow — the NOC engineer's job changes from active root-cause hunter to AI supervisor and exception handler.

This document is used by: HR (job descriptions), team leads (performance criteria), training designers (TASK-506 uses this as input).

#### Deliverables
- [ ] `docs/workforce/NOC_ENGINEER_ROLE_SPEC.md` with:
  1. **Role Overview**: Pre-Pedk.ai vs Post-Pedk.ai responsibilities comparison table
  2. **Primary Responsibilities (Post-Pedk.ai)**: SITREP review and approval, exception handling (cases where Pedk.ai is wrong), operator feedback submission, level transition decision authority
  3. **New Skills Required**: AI literacy (understanding confidence scores, reading decision traces), feedback quality (structured assessment, not just thumbs up/down), Dark Graph literacy (understanding divergence types)
  4. **Responsibilities Transferred to Pedk.ai**: Routine anomaly scanning, initial root cause hypothesis, ticket pre-population
  5. **Performance Criteria**: How NOC engineer performance is measured in an AI-augmented environment (quality of feedback, MTTR contribution, exception handling accuracy)
  6. **Escalation Decision Authority**: When the NOC engineer must escalate vs defer to Pedk.ai recommendation

#### Acceptance Criteria
- [ ] All 6 sections present
- [ ] Pre/Post comparison table has ≥ 8 responsibility rows
- [ ] Performance criteria are measurable

---

### TASK-506: Build hands-on training environment
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-012  
**Depends On:** TASK-203 (for synthetic divergence data), TASK-505 (for role spec)  
**Parallel With:** TASK-501 through TASK-505 (mostly — depends on 203 and 505 which are earlier phases)  

#### Context
§14 Lens 3: "T-012: Build hands-on training environment with Sleeping-Cell-KPI-Data." The existing training curriculum (`docs/training_curriculum.md`) is untested. A training environment provides NOC engineers with a sandboxed instance of Pedk.ai pre-loaded with synthetic data, a set of exercises, and a scoring mechanism.

This task creates the **exercise pack and auto-scorer** — not a new deployment (the engineer uses a standard dev deployment). The exercises are structured scenarios that the engineer must navigate using Pedk.ai's advisory interface.

#### Deliverables
- [ ] `training/exercises/` directory with 5 exercise files:
  - `EX-001_sleeping_cell_hunt.md` — scenario: 3 sleeping cells injected into synthetic data, goal: identify all 3 using only Pedk.ai SITREPs
  - `EX-002_phantom_node_cleanup.md` — scenario: 50 phantom nodes in CMDB, goal: generate divergence report and identify all phantom nodes
  - `EX-003_dark_edge_discovery.md` — scenario: 10 undocumented dependencies, goal: find at least 7 using Abeyance Memory snaps
  - `EX-004_feedback_quality.md` — scenario: 10 pre-generated SITREPs, goal: submit structured feedback for each; scoring based on feedback completeness
  - `EX-005_maintenance_window.md` — scenario: active ghost mask during planned maintenance, goal: correctly identify masked findings and unmasked real anomalies
- [ ] `training/auto_scorer.py` script:
  - Reads exercise submission from a JSON file (format specified in each exercise)
  - Compares against ground truth in synthetic data (`divergence_manifest.parquet`)
  - Outputs score: `{exercise: str, score: float, max_score: float, missed_items: list, false_positives: list}`
- [ ] Tests in `tests/test_auto_scorer.py`:
  - Test: perfect submission scores 100%
  - Test: empty submission scores 0%
  - Test: partial submission scores proportionally

#### Acceptance Criteria
- [ ] All 5 exercise files created
- [ ] `auto_scorer.py` runs without error on sample submissions
- [ ] `pytest tests/test_auto_scorer.py` passes

---

### TASK-507: Design cross-team SITREP escalation workflow
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-013  
**Depends On:** Nothing  
**Parallel With:** All Phase 5 tasks  

#### Context
§14 Lens 3: "T-013: Design cross-team SITREP escalation workflow. Score 1/5. No cross-team coordination protocol."

When Pedk.ai generates a SITREP, it may need to involve multiple teams: NOC (primary recipient), change management (if a change window is affected), security (if the SITREP involves an intrusion indicator), and capacity planning (if a congestion cascade is involved).

This document defines the routing rules and escalation triggers.

#### Deliverables
- [ ] `docs/workflows/SITREP_ESCALATION_WORKFLOW.md` with:
  1. **SITREP Routing Matrix**: Table mapping `{sitrep_type, severity, anomaly_category}` to `{primary_team, cc_teams, escalation_timeout_hours}`
  2. **Escalation Trigger Conditions**: When auto-escalate from L1 NOC to L2/L3 engineering (e.g., confidence > 0.9 and severity > HIGH and no acknowledgement within 30 minutes)
  3. **Multi-team Coordination Protocol**: When multiple teams receive the same SITREP, who has final decision authority; how conflicting assessments are resolved
  4. **SITREP Acknowledgement SLAs**: Per severity level — how quickly must each team acknowledge?
  5. **Runbook References**: Which NOC runbook section applies per SITREP type
- [ ] `services/sitrep_router.py` implementing the routing rules:
  - `route_sitrep(sitrep: SITREP) -> SITREPRouting` — returns primary team, cc teams, and SLA deadline
  - `SITREPRouting` dataclass: `primary_team: str, cc_teams: list[str], sla_deadline: datetime, escalation_path: list[str]`
  - Routing rules loaded from `docs/workflows/SITREP_ESCALATION_WORKFLOW.md` (YAML front-matter or separate YAML config)
- [ ] Tests in `tests/test_sitrep_router.py`:
  - Test: intrusion SITREP routes to security team
  - Test: sleeping cell SITREP routes to NOC with capacity planning CC
  - Test: HIGH severity with no acknowledgement after SLA triggers escalation

#### Acceptance Criteria
- [ ] `pytest tests/test_sitrep_router.py` passes
- [ ] Routing matrix covers all SITREP types defined in the spec

---

### TASK-508: Implement automated playbook generation
**Project:** Pedk.ai  
**Phase:** 5  
**Original Ref:** T-014  
**Depends On:** TASK-403 (evaluation pipeline for identifying high-confidence patterns)  
**Parallel With:** Other Phase 5 tasks  

#### Context
§14 Lens 3: "T-014: Implement automated playbook generation from high-confidence Decision Memory patterns."

When the same fault type has been resolved successfully more than 10 times with the same resolution path (high-confidence pattern), Pedk.ai should automatically generate a playbook document — a step-by-step remediation guide that NOC engineers can follow for future occurrences.

The playbook is generated by the LLM service, using the Decision Memory traces as context.

#### Deliverables
- [ ] `services/playbook_generator.py` with `PlaybookGenerator` class:
  - `find_eligible_patterns(tenant_id: UUID, min_occurrences: int = 10, min_success_rate: float = 0.8) -> list[Pattern]` — queries `DecisionTraceORM` for high-frequency, high-success patterns
  - `generate_playbook(pattern: Pattern) -> Playbook` — calls LLM service with Decision Memory traces as context, generates structured playbook
  - `Playbook` dataclass: `pattern_name: str, trigger_conditions: list[str], step_by_step: list[str], estimated_duration_minutes: int, success_criteria: str, rollback_steps: list[str]`
  - `save_playbook(playbook: Playbook, tenant_id: UUID) -> str` — saves to `docs/playbooks/{tenant_id}/{pattern_name}.md`
- [ ] POST `/api/v1/playbooks/generate/{pattern_id}` — triggers playbook generation for a specific pattern
- [ ] GET `/api/v1/playbooks/{tenant_id}` — lists all generated playbooks
- [ ] Tests (using mock LLM service):
  - Test: eligible patterns found from fixture data
  - Test: playbook generated from pattern has correct structure
  - Test: playbook is saved to correct path

#### Acceptance Criteria
- [ ] `pytest tests/test_playbook_generator.py` passes
- [ ] Generated playbook has all required fields
- [ ] Playbook markdown is parseable and has correct section headings

---

## PHASE 6 — INTEGRATION, VALIDATION & REFERENCE DEPLOYMENT
> **Goal:** End-to-end integration testing, reference deployment scenario, and operator Learning Hub. Tasks are mostly serial — each builds on the previous.

---

### TASK-601: End-to-end integration test — Offline PoC flow
**Project:** Pedk.ai  
**Phase:** 6  
**Original Ref:** T-009  
**Depends On:** TASK-301, TASK-302, TASK-303, TASK-304, TASK-203  
**Parallel With:** TASK-602  

#### Context
§12 Deployment Modes: "Offline PoC — Day 1 wedge: historical data analysis, Divergence Report generation. Read-only. Zero production access required." This is the mode that every new customer enters through. It must work end-to-end without any errors and produce a complete Divergence Report within 48 hours.

This test simulates a complete customer Day 1 engagement using the synthetic data from Sleeping-Cell-KPI-Data.

#### Deliverables
- [ ] `tests/integration/test_offline_poc_flow.py` that:
  1. Spins up a test database (SQLite or pg in Docker)
  2. Loads synthetic data: `cmdb_declared_entities.parquet`, KPI files, and a generated mock ticket archive
  3. Calls POST `/api/v1/dark-graph/analyze` with the three file uploads
  4. Polls GET `/api/v1/dark-graph/report/{job_id}` until complete or 120-second timeout
  5. Asserts the report contains ≥ 70% of the injected divergences from `divergence_manifest.parquet`
  6. Asserts the report JSON structure is complete (all required fields present)
  7. Asserts total execution time < 180 seconds
- [ ] A CLI wrapper script `scripts/run_offline_poc.py`:
  - Takes 3 file paths as arguments
  - Produces a human-readable Divergence Report to stdout
  - Exits 0 on success, non-zero on failure

#### Acceptance Criteria
- [ ] `pytest tests/integration/test_offline_poc_flow.py` passes with 0 failures
- [ ] `python scripts/run_offline_poc.py --help` shows correct usage
- [ ] CLI script produces readable output with divergence count, type breakdown, and top 10 high-confidence findings

---

### TASK-602: End-to-end integration test — Shadow Mode flow
**Project:** Pedk.ai  
**Phase:** 6  
**Original Ref:** T-009  
**Depends On:** TASK-101, TASK-102, TASK-107, TASK-304  
**Parallel With:** TASK-601  

#### Context
§12 Deployment Modes: "Shadow Mode — Parallel-run alongside existing tools; proves accuracy without taking control. Read-only production data feeds (Kafka tap, syslog mirror). No write access to any system."

Shadow Mode is the mode after the customer has seen the Offline PoC report and trusted Pedk.ai enough to connect live read-only feeds. This integration test simulates a shadow mode session using Kafka + synthetic data.

#### Deliverables
- [ ] `tests/integration/test_shadow_mode_flow.py` that:
  1. Starts a Kafka test container (using `testcontainers-python`)
  2. Publishes synthetic KPI events to Kafka topics at realistic volume (1000 events/second)
  3. Verifies Pedk.ai consumes and processes events without backlog growth
  4. Verifies sleeping cell detector fires when a synthetic sleeping cell scenario is injected
  5. Verifies Ghost Mask suppresses anomaly findings during a synthetic maintenance window
  6. Verifies Abeyance Memory stores unresolved fragments
  7. Asserts no write operations to any external system (verify by checking for any non-database writes)

#### Acceptance Criteria
- [ ] `pytest tests/integration/test_shadow_mode_flow.py` passes
- [ ] Kafka consumer lag < 5 seconds at 1000 events/second input rate
- [ ] Zero external write operations confirmed

---

### TASK-603: Create operator-facing Learning Hub
**Project:** Pedk.ai  
**Phase:** 6  
**Original Ref:** T-015  
**Depends On:** TASK-504, TASK-505, TASK-506, TASK-507  
**Parallel With:** Nothing — final phase  

#### Context
§14 Lens 3: "T-015: Create operator-facing 'Pedk.ai Learning Hub' knowledge base." This is the published knowledge base that NOC engineers access during onboarding and ongoing operations. It is NOT internal engineering documentation — it is written for NOC engineers who are not product engineers.

#### Deliverables
- [ ] `docs/learning_hub/` directory with:
  - `README.md` — index page with navigation
  - `01_what_is_pedk.md` — plain-English explanation of what Pedk.ai does (no jargon)
  - `02_understanding_sitrreps.md` — how to read a SITREP, what each section means, what to do with it
  - `03_dark_graph_explained.md` — what the Dark Graph is, the 6 divergence types, with real examples
  - `04_feedback_guide.md` — how and why to provide feedback; the three feedback channels; why structured feedback matters
  - `05_autonomy_levels.md` — the 4 levels explained for operators (not engineers); what changes at each level; how to request a level change
  - `06_training_exercises.md` — link to training exercises (TASK-506), pre-requisites, how to score yourself
  - `07_faq.md` — at least 15 frequently asked questions from a NOC engineer perspective
- [ ] All documents written at reading level appropriate for experienced NOC engineers (not software engineers)
- [ ] All documents cross-reference relevant spec sections and runbook sections

#### Acceptance Criteria
- [ ] All 8 files exist with non-trivial content (> 300 words each)
- [ ] FAQ has ≥ 15 Q&A pairs
- [ ] No document contains internal engineering jargon without explanation
- [ ] All cross-references point to files that exist (no broken links)

---

### TASK-604: Final backlog closure audit
**Project:** Pedk.ai + Sleeping-Cell-KPI-Data  
**Phase:** 6  
**Original Ref:** All T-002 through T-028  
**Depends On:** All previous tasks  
**Parallel With:** Nothing  

#### Context
This task closes the loop. It verifies that every item in the original task backlog (T-002 through T-028) has been addressed by at least one task in this file, and that no new technical debt has been introduced.

#### Deliverables
- [ ] `audit/backlog_closure_report.md` with:
  - For each original backlog item T-002 through T-028: the NEW_TASKS.md task ID(s) that address it, and the acceptance criteria that confirm closure
  - List of any new issues discovered during implementation (items not in original backlog)
  - Overall test count before vs after (from TASK-008 baseline)
  - Coverage report summary

#### Acceptance Criteria
- [ ] Every T-002 through T-028 item mapped to at least one TASK-XXX entry
- [ ] `pytest` full suite runs with < 5% failure rate
- [ ] No TODO/FIXME/HACK comments introduced by any task in this backlog (grep confirms)

---

## SUMMARY TABLE

| Task ID | Title | Phase | Project | Original Ref | Priority |
|---------|-------|:-----:|---------|-------------|:--------:|
| TASK-001 | Audit sleeping cell wiring | 0 | Pedk.ai | T-024 | 🔴 |
| TASK-002 | Audit Dark Graph completeness | 0 | Pedk.ai | T-025 | 🔴 |
| TASK-003 | Audit Abeyance Memory gaps | 0 | Pedk.ai | T-016, T-026 | 🔴 |
| TASK-004 | Audit operator feedback gaps | 0 | Pedk.ai | T-003, T-007 | 🔴 |
| TASK-005 | Audit fusion and causal modules | 0 | Pedk.ai | T-017, T-023 | 🟡 |
| TASK-006 | Audit synthetic data generator | 0 | Sleeping-Cell | T-018 to T-022 | 🔴 |
| TASK-007 | Audit frontend architecture | 0 | Pedk.ai | T-027 | 🟡 |
| TASK-008 | Audit test suite coverage | 0 | Pedk.ai | T-028 | 🟡 |
| TASK-101 | Wire sleeping cell detector | 1 | Pedk.ai | T-024 | 🔴 |
| TASK-102 | Abeyance Memory decay scoring | 1 | Pedk.ai | T-016 | 🔴 |
| TASK-103 | Replace UUID V4 identifiers | 1 | Sleeping-Cell | T-018 | 🔴 |
| TASK-104 | FusionMethodologyFactory skeleton | 1 | Pedk.ai | T-017 | 🟡 |
| TASK-105 | Dempster-Shafer fusion | 1 | Pedk.ai | T-017 | 🟡 |
| TASK-106 | Transfer Entropy causal inference | 1 | Pedk.ai | T-023 | 🟡 |
| TASK-107 | Persistent event bus (Redis) | 1 | Pedk.ai | T-008 | 🟡 |
| TASK-201 | Diurnal/seasonal KPI patterns | 2 | Sleeping-Cell | T-020 | 🔴 |
| TASK-202 | Propagation delay profiles | 2 | Sleeping-Cell | T-021 | 🟡 |
| TASK-203 | CMDB degradation calibration | 2 | Sleeping-Cell | T-022 | 🔴 |
| TASK-204 | Scenario validation framework | 2 | Sleeping-Cell | T-019 | 🟡 |
| TASK-205 | Abeyance cold storage pipeline | 2 | Pedk.ai | T-016 | 🔴 |
| TASK-301 | Dark Graph Divergence Report | 3 | Pedk.ai | T-025 | 🔴 |
| TASK-302 | Datagerry CMDB sync adapter | 3 | Pedk.ai | T-025 | 🔴 |
| TASK-303 | CasinoLimit telemetry parser | 3 | Pedk.ai | T-025 | 🔴 |
| TASK-304 | Topological Ghost Masks | 3 | Pedk.ai | T-025 | 🟡 |
| TASK-305 | PCMCI causal graph discovery | 3 | Pedk.ai | T-023 | 🟡 |
| TASK-306 | Abeyance multi-modal matching | 3 | Pedk.ai | T-026 | 🟡 |
| TASK-401 | Behavioural observation pipeline | 4 | Pedk.ai | T-003 | 🔴 |
| TASK-402 | Structured operator assessment | 4 | Pedk.ai | T-007 | 🟡 |
| TASK-403 | Continuous evaluation pipeline | 4 | Pedk.ai | T-005 | 🟡 |
| TASK-404 | Frontend decomposition | 4 | Pedk.ai | T-027 | 🟡 |
| TASK-405 | Test suite — safety gate coverage | 4 | Pedk.ai | T-028 | 🟡 |
| TASK-501 | OFCOM pre-notification document | 5 | Pedk.ai | T-006 | 🔴 |
| TASK-502 | ICO DPIA | 5 | Pedk.ai | T-006 | 🔴 |
| TASK-503 | Autonomous Safety Whitepaper | 5 | Pedk.ai | T-006 | 🔴 |
| TASK-504 | AI Behaviour Specification | 5 | Pedk.ai | T-002 | 🟡 |
| TASK-505 | NOC Engineer Role Specification | 5 | Pedk.ai | T-011 | 🟡 |
| TASK-506 | Training environment & exercises | 5 | Pedk.ai | T-012 | 🟡 |
| TASK-507 | SITREP escalation workflow | 5 | Pedk.ai | T-013 | 🟢 |
| TASK-508 | Automated playbook generation | 5 | Pedk.ai | T-014 | 🟢 |
| TASK-601 | E2E test — Offline PoC flow | 6 | Pedk.ai | T-009 | 🔴 |
| TASK-602 | E2E test — Shadow Mode flow | 6 | Pedk.ai | T-009 | 🟡 |
| TASK-603 | Operator Learning Hub | 6 | Pedk.ai | T-015 | 🟢 |
| TASK-604 | Final backlog closure audit | 6 | Both | All | 🔴 |

**Total tasks: 44**  
**Original backlog items covered: T-002 through T-028 (all 27)**  
**Net new tasks (decomposed from originals): 17**

---

## PARALLELISM GUIDE FOR AGENT SCHEDULING

```
Phase 0 ──────────────────────────────────────────────────────────────
  TASK-001, 002, 003, 004, 005, 006, 007, 008 [ALL PARALLEL]

Phase 1 (after Phase 0 complete) ─────────────────────────────────────
  Stream A: TASK-101 (needs 001) → feeds TASK-601
  Stream B: TASK-102 (needs 003) → feeds TASK-205
  Stream C: TASK-103 (needs 006) → feeds TASK-201, 202, 203, 204
  Stream D: TASK-104 (needs 005) → TASK-105 (serial, needs 104)
  Stream E: TASK-106 (needs 005) → TASK-305 (serial, needs 106)
  Stream F: TASK-107 (independent) → feeds TASK-401

Phase 2 (streams C from Phase 1, B from Phase 1) ─────────────────────
  TASK-201, 202, 203, 204 [ALL PARALLEL, all need TASK-103]
  TASK-205 [needs TASK-102]

Phase 3 (after Phase 2 complete) ─────────────────────────────────────
  Stream A: TASK-301 (needs 002, 203) 
  Stream B: TASK-302 (needs 002)
  Stream C: TASK-303 (needs 002)
  Stream D: TASK-304 (needs 002)
  Stream E: TASK-305 (needs 106) [serial from Phase 1 Stream E]
  Stream F: TASK-306 (needs 003, 102, 205)
  [301, 302, 303, 304, 306 all parallel; 305 serial after 106]

Phase 4 (after Phase 3 complete) ─────────────────────────────────────
  TASK-401 (needs 004, 107)
  TASK-402 (needs 004) [parallel with 401]
  TASK-403 (needs 301, 401) [serial after 301 and 401]
  TASK-404 (needs 007) [parallel with 401, 402]
  TASK-405 (needs 008) [parallel with 401, 402, 404]

Phase 5 (can run alongside Phase 4 — no code dependencies) ───────────
  TASK-501, 502, 503, 504, 505 [ALL PARALLEL]
  TASK-506 (needs 203, 505)
  TASK-507 [parallel with 501-505]
  TASK-508 (needs 403)

Phase 6 (after Phases 4 and 5 complete) ──────────────────────────────
  TASK-601 (needs 301, 302, 303, 304, 203) [parallel with 602]
  TASK-602 (needs 101, 102, 107, 304) [parallel with 601]
  TASK-603 (needs 504, 505, 506, 507)
  TASK-604 [final — needs everything]
```

---

*End of NEW_TASKS.md*  
*Document covers all T-002 through T-028 from PRODUCT_SPEC.md §17 Task Backlog*  
*44 atomic tasks across 7 phases, targeting zero outstanding backlog*
