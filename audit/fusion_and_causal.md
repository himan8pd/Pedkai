# Audit Report: Evidence Fusion and Causal Inference Modules
**Date**: 2026-03-10
**Scope**: Pedkai Backend Codebase
**Task**: TASK-005 - Audit evidence fusion and causal inference modules

---

## Executive Summary

The Pedkai codebase contains a **Granger Causality** implementation for time-series causal analysis, but **NO Noisy-OR evidence fusion** module was found. The codebase includes decision trace memory with a confidence scoring system that loosely incorporates evidence (via `memory_hits` and `causal_evidence_count` fields), but does not implement a formal probabilistic fusion mechanism.

---

## 1. Granger Causality Implementation

### Location
**File**: `/Users/himanshu/Projects/Pedkai/anops/causal_analysis.py`

### Class/Function Names
- **Class**: `CausalAnalyzer`
- **Primary Method**: `async test_granger_causality(...)`
- **Supporting Methods**:
  - `async get_available_metrics(entity_id, hours)` — Dynamic metric discovery
  - `async _fetch_metric_series(entity_id, metric_name, hours)` — Time-series data retrieval
  - `_ensure_stationary(series)` — Augmented Dickey-Fuller stationarity testing
  - `async find_causes_for_anomaly(entity_id, anomalous_metric, max_lag)` — Discovery of causal drivers

### Interface Signature

**Input Types:**
```python
entity_id: str
cause_metric: str
effect_metric: str
max_lag: int = 4
significance_level: float = 0.05
```

**Output Type:**
```python
Dict[str, Any] = {
    "causes": bool,              # True if causality detected
    "p_value": float,            # p-value from F-test (≤ 0.05 = significant)
    "best_lag": int,             # Lag at which causality is strongest
    "cause_metric": str,
    "effect_metric": str,
    "stationarity_fixed": bool,  # Whether series were differenced
    "error": Optional[str]       # Error message if test failed
}
```

### Python Package Dependencies
- `numpy` (≥1.26.0) — Array operations
- `sqlalchemy` (≥2.0.25) — Database queries
- `sqlalchemy.ext.asyncio` — Async session management
- `statsmodels` (≥0.14.0) — `adfuller()` for ADF test, `grangercausalitytests()`
- `datetime` — Timestamp handling
- `typing` — Type hints

### Key Design Decisions

1. **Minimum Observations Guard**: `MIN_OBSERVATIONS = 100` to ensure statistical power (Telco MTTR context)
2. **Stationarity Enforcement**: Applies first-order differencing (`np.diff()`) if ADF test fails
3. **Dynamic Metric Discovery**: Queries available metrics at test time rather than using hardcoded lists
4. **Multi-lag Best Fit**: Tests lags 1 to `max_lag` and returns the lag with lowest p-value

---

## 2. Noisy-OR Implementation

### Status
**NOT FOUND** — No Noisy-OR module exists in the codebase.

### Grep Results
```bash
grep -rn "noisy.or|NoisyOR|noisy_or|NoisyOr" /Users/himanshu/Projects/Pedkai --include="*.py"
# Returns: (no matches)
```

---

## 3. Evidence Fusion Mechanisms (Alternative Pattern Found)

While a formal Noisy-OR is absent, the codebase implements **decision confidence scoring** that loosely incorporates multiple evidence sources:

### Location
**Files**:
- `/Users/himanshu/Projects/Pedkai/backend/app/services/causal_models.py` — Template matching
- `/Users/himanshu/Projects/Pedkai/backend/app/models/decision_trace.py` — Decision trace schema
- `/Users/himanshu/Projects/Pedkai/backend/app/services/decision_repository.py` — Calibration logic

### Class/Function Names

#### CausalModelLibrary (Template-Based Evidence Matching)
- **Class**: `CausalModelLibrary`
- **Method**: `match_causal_templates(anomalies: List[Dict[str, Any]]) → List[Dict[str, Any]]`

**Input**:
```python
anomalies: List[Dict[str, Any]] = [
    {"entity_id": str, "entity_type": str, "metric_name": str, "value": float},
    ...
]
```

**Output**:
```python
List[Dict[str, Any]] = [
    {
        "template_id": str,
        "description": str,
        "confidence": float,      # From CausalTemplate.confidence (0.0-1.0)
        "evidence": {
            "causes": [str],      # Entity IDs that triggered the cause_metric
            "effects": [str]      # Entity IDs that triggered the effect_metric
        }
    },
    ...
]
```

#### DecisionTrace Confidence Scoring
- **Class**: `DecisionTrace` (Pydantic model)
- **Confidence Fields**:
  - `confidence_score: float` (0.0-1.0) — AI decision confidence
  - `memory_hits: int` — Count of similar past decisions found
  - `causal_evidence_count: int` — Count of causal relationships detected
  - `feedback_score: int` (aggregate) — Operator feedback accumulated over time

**Calibration Method** (in `DecisionTraceRepository`):
```python
async def get_calibration_stats(
    memory_hits: int,
    causal_count: int,
) → Dict = {
    "avg_score": float | None,      # Historical avg operator feedback
    "total_votes": int              # Number of past decisions in this bin
}
```

### Heuristic Fusion Logic

**No formal Bayesian fusion is implemented.** Instead:

1. **Template Matching**: Binary AND over (cause_metric ∧ effect_metric) — anomalies must match BOTH
2. **Confidence Propagation**: Uses `CausalTemplate.confidence` directly (hardcoded 0.90-0.98 per template)
3. **Historical Calibration**: Uses `memory_hits + causal_evidence_count` as a bin key to look up past outcome distributions

### Python Package Dependencies
- `pydantic` (≥2.5.0) — Data validation
- `yaml` (built-in via PyYAML, implicitly required)
- `structlog` — Logging (via `get_logger()`)
- `sqlalchemy` — Database queries
- `sqlalchemy.ext.asyncio` — Async session management

---

## 4. Abstract Base Classes & Interfaces

### LLMAdapter Abstraction
**File**: `/Users/himanshu/Projects/Pedkai/backend/app/services/llm_adapter.py`

```python
from abc import ABC, abstractmethod

class LLMAdapter(ABC):
    """Abstract base class for LLM adapters."""

    @abstractmethod
    async def embed(self, text: str) → list[float]:
        """Generate an embedding vector for the given text."""
        ...
```

**Purpose**: Decouples provider-specific implementations (Gemini, on-prem) from decision memory embedding.
**Relevance to Fusion**: Used to generate embeddings for similar decision retrieval (not direct fusion).

### BSSAdapter Abstraction
**File**: `/Users/himanshu/Projects/Pedkai/backend/app/services/bss_adapter.py`

```python
from abc import ABC, abstractmethod

class BSSAdapter(ABC):
    """Abstract BSS adapter."""

    @abstractmethod
    async def get_revenue_at_risk(self, customer_ids: List[UUID]) → RevenueResult:
        ...
```

**Purpose**: Vendor-agnostic billing/revenue integration.
**Relevance to Fusion**: Evidence source for impact assessment (used in decision context).

### No Abstract Evidence Fusion Base Class
- **Status**: NONE FOUND
- `EvidenceFusion` class: NOT FOUND
- `CausalMethod` base class: NOT FOUND

---

## 5. Dependency Summary

### Scientific/Causal AI Stack
```
numpy                ≥1.26.0       # Array operations, differencing
statsmodels          ≥0.14.0       # adfuller, grangercausalitytests
sentence-transformers ≥2.3.0       # Embeddings for decision similarity (not causal fusion)
```

### Database & ORM
```
sqlalchemy           ≥2.0.25       # Query building
sqlalchemy.ext.asyncio              # Async session management
pgvector             ≥0.2.4        # Vector similarity (pgvector type)
asyncpg              ≥0.29.0       # PostgreSQL async driver
```

### Framework & Data
```
fastapi              ≥0.109.0      # REST API
pydantic             ≥2.5.0        # Schema validation
google-genai                        # Gemini embedding/generation
httpx                ≥0.26.0       # Async HTTP for embedding calls
```

---

## 6. Testing Coverage

### Unit Tests
**File**: `/Users/himanshu/Projects/Pedkai/tests/unit/test_causal_models.py`

**Tests Found**:
1. `test_causal_matching_power_failure()` — Template match with cause AND effect
2. `test_causal_matching_no_match()` — No matching template
3. `test_causal_matching_partial_match()` — Only cause, no effect (returns empty)

**Test Scope**: CausalModelLibrary template matching only (NOT Granger Causality tests).

### Validation Tests
**File**: `/Users/himanshu/Projects/Pedkai/tests/validation/test_live_data_causal.py`
*(File exists but not fully read; likely integration tests against live TimescaleDB)*

---

## 7. Architecture Findings

### What IS Implemented (Evidence Fusion Approximation)
1. **Causal Template Library** (expert-defined patterns)
2. **Confidence Score Aggregation** (memory_hits + causal_evidence_count)
3. **Historical Calibration** (empirical outcome distribution by evidence bin)
4. **Multi-Source Confidence** (decision score = f(template_confidence, memory_hits, causal_count, feedback))

### What IS NOT Implemented (Probabilistic Fusion)
- No Noisy-OR gate implementation
- No Bayesian network structure learning
- No probability propagation or belief updates
- No formal modeling of evidence independence assumptions
- No handling of "explaining away" (v-structure blocking)

### Design Philosophy
The codebase prioritizes **practical, interpretable decision making** over formal probabilistic graphical models:
- Hard constraints and options-based reasoning (Decision Trace)
- Expert-defined causal templates (CausalModelLibrary)
- Empirical confidence calibration (historical outcome tracking)
- Granger Causality for *statistical discovery* (not real-time fusion)

---

## 8. Data Flow for Decision Confidence

```
┌──────────────────────────────────┐
│   Anomalies Detected             │
├──────────────────────────────────┤
│ 1. Run Granger tests             │
│    (measure causal relationships) │
│    → causal_evidence_count       │
├──────────────────────────────────┤
│ 2. Match causal templates        │
│    (expert rules)                │
│    → template_confidence         │
├──────────────────────────────────┤
│ 3. Retrieve similar decisions    │
│    (pgvector + feedback boost)   │
│    → memory_hits                 │
├──────────────────────────────────┤
│ 4. Look up calibration stats     │
│    (historical outcomes by bin)  │
│    → expected_operator_score     │
├──────────────────────────────────┤
│ 5. Create DecisionTrace          │
│    confidence_score = f(...)     │
│    (decision_maker + context)    │
└──────────────────────────────────┘
```

---

## 9. Recommendations for Future Enhancement

### If Noisy-OR Evidence Fusion Is Required:
1. **Implement `EvidenceFusionBase` ABC** with:
   - `async fuse(evidence_sources: List[Evidence]) → float` (belief in hypothesis)
   - `set_inhibition_probabilities(source_pairs: Dict)` (independence model)

2. **Create `NoisyORGate` class** implementing:
   - Noisy-OR gate formula: `P(H) = 1 - ∏(1 - leak - w_i * P(E_i))`
   - Leaky gate parameter (background belief)
   - Weight learning via EM (optional)

3. **Integrate with DecisionTrace** confidence scoring:
   - Use fused belief as input to `confidence_score` calculation
   - Store evidence inhibition relationships in decision context

4. **Add causal graph learning** (optional):
   - Use Granger Causality results to build directed acyclic graph (DAG)
   - Infer v-structure blocking relationships
   - Apply causal Bayesian network inference

### Current Strengths:
- ✅ Granger Causality for discovering temporal causality
- ✅ Decision memory with historical outcome feedback
- ✅ Expert causal templates for human-guided inference
- ✅ Operator feedback loop for calibration

### Current Gaps:
- ❌ No explicit evidence fusion probability model
- ❌ No handling of evidence dependencies
- ❌ No real-time belief propagation
- ❌ Limited to pairwise causal relationships (Granger)

---

## 10. Summary Table

| Component | Location | Status | Dependencies |
|-----------|----------|--------|--------------|
| **Granger Causality** | `anops/causal_analysis.py` | ✅ FOUND | statsmodels, numpy, sqlalchemy |
| **Noisy-OR** | — | ❌ NOT FOUND | — |
| **Evidence Fusion** (Template) | `backend/app/services/causal_models.py` | ⚠️ PARTIAL | pydantic, yaml |
| **Confidence Scoring** | `backend/app/models/decision_trace.py` | ✅ FOUND | pydantic |
| **Calibration Logic** | `backend/app/services/decision_repository.py` | ✅ FOUND | sqlalchemy |
| **Abstract Base Classes** | `backend/app/services/*_adapter.py` | ✅ FOUND | abc |

---

## Appendix A: File Listing

### Core Causal/Fusion Modules
- `/Users/himanshu/Projects/Pedkai/anops/causal_analysis.py` — CausalAnalyzer class
- `/Users/himanshu/Projects/Pedkai/backend/app/services/causal_models.py` — CausalTemplate library
- `/Users/himanshu/Projects/Pedkai/backend/app/models/decision_trace.py` — Decision confidence fields
- `/Users/himanshu/Projects/Pedkai/backend/app/services/decision_repository.py` — Repository with calibration

### Tests
- `/Users/himanshu/Projects/Pedkai/tests/unit/test_causal_models.py` — Unit tests (template matching)
- `/Users/himanshu/Projects/Pedkai/tests/validation/test_live_data_causal.py` — Integration tests

### Adapter Abstractions
- `/Users/himanshu/Projects/Pedkai/backend/app/services/llm_adapter.py` — LLMAdapter ABC
- `/Users/himanshu/Projects/Pedkai/backend/app/services/bss_adapter.py` — BSSAdapter ABC

---

**Audit Completed**: 2026-03-10
**Auditor**: Claude Code Discovery Agent
