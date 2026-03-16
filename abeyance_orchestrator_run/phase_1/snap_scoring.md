# Snap Engine Scoring Redesign -- Per-Dimension Scoring with Mask-Aware Weight Redistribution

**Task**: T1.4 -- Snap Engine Scoring Redesign
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Remediates**: F-2.4 (SEVERE), F-6.2 (CRITICAL)

---

## 1. Problem Statement

The v2.0 snap engine has two critical defects in its scoring path:

1. **F-6.2 (CRITICAL)**: The enrichment chain computes an `embedding_mask` (4-element boolean array tracking which sub-vectors are valid) and stores it on every fragment. The snap engine never reads this mask. It computes cosine similarity over the full concatenated 1536-dim `enriched_embedding` regardless of which sub-vectors contain real data versus zeros. When an LLM call fails, 75% of the embedding becomes zeros, and the cosine similarity produces meaningless scores.

2. **F-2.4 (SEVERE)**: The five weight profiles (`DARK_EDGE`, `DARK_NODE`, `IDENTITY_MUTATION`, `PHANTOM_CI`, `DARK_ATTRIBUTE`) are hand-tuned constants with no empirical validation, no sensitivity analysis, and no documentation of derivation methodology.

Both defects exist in the current `_score_pair()` method which computes a single cosine similarity over the concatenated vector and applies failure-mode-specific weights to a 4-component score (semantic, topological, entity overlap, operational).

---

## 2. v3.0 Embedding Architecture

The v3.0 schema stores embeddings as **separate columns** rather than a single concatenated vector:

| Column | Type | Dimension | Always Valid |
|---|---|---|---|
| `emb_semantic` | `Vector(1536)` | 1536 | No |
| `emb_topological` | `Vector(1536)` | 1536 | No |
| `emb_temporal` | `Vector(256)` | 256 | Yes |
| `emb_operational` | `Vector(1536)` | 1536 | No |
| `mask_semantic` | `Boolean` | -- | N/A |
| `mask_topological` | `Boolean` | -- | N/A |
| `mask_operational` | `Boolean` | -- | N/A |

**Mask semantics**: If the T-VEC (text-to-vector embedding call) for a dimension fails, the column is `NULL` and the corresponding mask is `FALSE`. There is no zero-filling. Temporal is always valid (deterministic computation, no external dependency). Entity overlap (Jaccard) is always available because it operates on extracted entity identifiers, not embeddings.

---

## 3. Per-Dimension Similarity Functions

### 3.1 Embedding-Based Dimensions

For each embedding dimension `d` in `{semantic, topological, temporal, operational}`:

```
sim_d(A, B) = cosine(emb_d_A, emb_d_B)
            = dot(emb_d_A, emb_d_B) / (||emb_d_A|| * ||emb_d_B||)
```

**Precondition**: Both `emb_d_A` and `emb_d_B` must be non-NULL.

**Degenerate input guard**: If either vector has L2 norm < 1e-10, return 0.0. This prevents division by zero without masking a valid zero-vector (which should not exist for normalized LLM embeddings).

**Output range**: `[-1.0, 1.0]` for raw cosine. Clamped to `[0.0, 1.0]` before use in weighted combination, because negative cosine similarity between fragments indicates no meaningful correlation (not anti-correlation).

```python
def _cosine_sim_clamped(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    raw = float(np.dot(a, b) / (norm_a * norm_b))
    return max(0.0, min(1.0, raw))
```

### 3.2 Entity Overlap (Jaccard)

```
sim_entity(A, B) = |entities_A intersection entities_B| / |entities_A union entities_B|
```

If both entity sets are empty, return 0.0.

**Always available**: Entity overlap operates on `FragmentEntityRefORM` rows (extracted identifiers), not on embeddings. Even if all embedding calls fail, entity extraction (regex fallback) provides identifiers.

**Output range**: `[0.0, 1.0]` by definition.

### 3.3 Summary of Five Similarity Dimensions

| Dimension | Symbol | Source | Can Be Unavailable | Computation |
|---|---|---|---|---|
| Semantic | `S_sem` | `emb_semantic` | Yes (LLM failure) | `cosine(emb_semantic_A, emb_semantic_B)` clamped to [0,1] |
| Topological | `S_topo` | `emb_topological` | Yes (LLM failure / no neighbourhood) | `cosine(emb_topological_A, emb_topological_B)` clamped to [0,1] |
| Temporal | `S_temp` | `emb_temporal` | No (deterministic) | `cosine(emb_temporal_A, emb_temporal_B)` clamped to [0,1] |
| Operational | `S_oper` | `emb_operational` | Yes (LLM failure) | `cosine(emb_operational_A, emb_operational_B)` clamped to [0,1] |
| Entity Overlap | `S_ent` | Entity refs | No (regex fallback) | `Jaccard(entities_A, entities_B)` |

---

## 4. Mask Enforcement

### 4.1 Availability Predicate

A dimension `d` is **available** for a pair `(A, B)` if and only if both fragments have the mask set to TRUE for that dimension:

```
available_d(A, B) = mask_d_A AND mask_d_B
```

For the embedding-based dimensions:

```
available_semantic(A, B)     = A.mask_semantic AND B.mask_semantic
available_topological(A, B)  = A.mask_topological AND B.mask_topological
available_operational(A, B)  = A.mask_operational AND B.mask_operational
```

Temporal and entity overlap are always available:

```
available_temporal(A, B)      = TRUE   (always)
available_entity_overlap(A, B) = TRUE   (always)
```

### 4.2 Enforcement Rule

If `available_d(A, B) = FALSE` for an embedding dimension, the snap engine MUST NOT compute cosine similarity for that dimension. The similarity score for that dimension is undefined (not zero). The dimension is excluded from the weighted combination and its weight is redistributed per Section 5.

**Rationale**: Computing cosine on a NULL column would crash. Computing cosine on a zero-filled column would produce 0.0, which is a false signal (it asserts "these fragments are dissimilar on this dimension") when the true state is "we have no information on this dimension." Exclusion with weight redistribution is the only correct approach.

---

## 5. Weight Redistribution Formula

### 5.1 Base Weight Profile

A weight profile `P` defines five weights:

```
P = { w_sem, w_topo, w_temp, w_oper, w_ent }
```

**Constraint**: `w_sem + w_topo + w_temp + w_oper + w_ent = 1.0`

### 5.2 Available and Unavailable Partitions

Given a pair `(A, B)`, partition the five dimensions into:

- `D_avail` = set of dimensions where `available_d(A, B) = TRUE`
- `D_unavail` = set of dimensions where `available_d(A, B) = FALSE`

Since temporal and entity overlap are always available, `D_avail` always contains at least `{temporal, entity_overlap}`.

Therefore `|D_avail| >= 2` for every pair, and the sum of available weights is always > 0.

### 5.3 Proportional Redistribution

The unavailable weight mass is distributed proportionally to available dimensions:

```
total_unavailable = SUM(w_d for d in D_unavail)
total_available   = SUM(w_d for d in D_avail)

For each d in D_avail:
    w_d_adjusted = w_d + w_d * (total_unavailable / total_available)
                 = w_d * (1.0 / total_available)
                 = w_d / total_available
```

**Simplified form**: The adjusted weight for each available dimension is its base weight divided by the sum of all available base weights. This is equivalent to renormalizing the available weights to sum to 1.0.

```
w_d_adjusted = w_d / SUM(w_i for i in D_avail)
```

**Proof that adjusted weights sum to 1.0**:

```
SUM(w_d_adjusted for d in D_avail) = SUM(w_d / total_available for d in D_avail)
                                    = total_available / total_available
                                    = 1.0
```

### 5.4 Worked Examples

**Example 1: All dimensions available**

Given `P = { w_sem=0.25, w_topo=0.20, w_temp=0.15, w_oper=0.15, w_ent=0.25 }`:

`total_available = 1.0`

Adjusted weights = base weights (unchanged).

**Example 2: Semantic unavailable**

`D_avail = {topo, temp, oper, ent}`, `D_unavail = {sem}`

`total_available = 0.20 + 0.15 + 0.15 + 0.25 = 0.75`

```
w_topo_adj = 0.20 / 0.75 = 0.2667
w_temp_adj = 0.15 / 0.75 = 0.2000
w_oper_adj = 0.15 / 0.75 = 0.2000
w_ent_adj  = 0.25 / 0.75 = 0.3333
                    Sum   = 1.0000
```

**Example 3: Semantic, topological, and operational all unavailable (LLM total outage)**

`D_avail = {temp, ent}`, `D_unavail = {sem, topo, oper}`

`total_available = 0.15 + 0.25 = 0.40`

```
w_temp_adj = 0.15 / 0.40 = 0.375
w_ent_adj  = 0.25 / 0.40 = 0.625
                    Sum   = 1.000
```

This graceful degradation means the system continues operating during LLM outages using only temporal similarity and entity overlap, with appropriate weight distribution.

### 5.5 Bounded Arithmetic Guarantee

**Claim**: The redistribution formula cannot produce floating-point instability.

**Proof**:
1. `total_available >= w_temp + w_ent > 0` because temporal and entity overlap are always available and their weights are positive (enforced by profile validation, Section 6.3).
2. Division by `total_available` is safe because `total_available > 0`.
3. Each `w_d_adjusted` is in `(0, 1]` because `0 < w_d <= total_available`.
4. The final weighted score is a convex combination of values in `[0.0, 1.0]`, so it is in `[0.0, 1.0]`.

No additional clamping is needed on the weighted combination itself, though the implementation MUST clamp the final score to `[0.0, 1.0]` as a defense-in-depth measure (INV-3).

---

## 6. Weight Profiles

### 6.1 Profile Structure

Each profile maps a failure mode to five base weights:

```python
@dataclass(frozen=True)
class WeightProfile:
    failure_mode: str
    w_sem: float       # semantic embedding weight
    w_topo: float      # topological embedding weight
    w_temp: float      # temporal embedding weight
    w_oper: float      # operational embedding weight
    w_ent: float       # entity overlap (Jaccard) weight

    def __post_init__(self):
        total = self.w_sem + self.w_topo + self.w_temp + self.w_oper + self.w_ent
        assert abs(total - 1.0) < 1e-9, f"Weights must sum to 1.0, got {total}"
        for name in ('w_sem', 'w_topo', 'w_temp', 'w_oper', 'w_ent'):
            val = getattr(self, name)
            assert 0.0 < val <= 1.0, f"{name} must be in (0, 1], got {val}"
```

**Invariant**: Every weight must be strictly positive (`> 0.0`). A zero weight would mean the dimension is structurally irrelevant to the failure mode, which should be expressed by making the weight very small (e.g., 0.05) rather than zero. Zero weights break the redistribution formula's proportionality guarantee (a dimension with weight 0 receives 0 redistributed weight, which is correct, but it also contributes 0 to the denominator, which could mask information loss).

### 6.2 Initial Weight Profiles (Estimates Pending Empirical Validation)

These weights are **initial estimates** derived from domain reasoning about what signals matter most for each failure mode. They have NOT been validated empirically. See Section 6.4 for the validation methodology.

```python
WEIGHT_PROFILES = {
    "DARK_EDGE": WeightProfile(
        failure_mode="DARK_EDGE",
        w_sem=0.15, w_topo=0.30, w_temp=0.10, w_oper=0.15, w_ent=0.30,
    ),
    # Rationale: Dark edges are missing connections between known nodes.
    # Topological proximity and entity overlap dominate because the signal
    # is in which nodes are involved and how they relate structurally.

    "DARK_NODE": WeightProfile(
        failure_mode="DARK_NODE",
        w_sem=0.25, w_topo=0.10, w_temp=0.10, w_oper=0.20, w_ent=0.35,
    ),
    # Rationale: Dark nodes are unknown entities appearing in telemetry.
    # Entity overlap is the strongest signal (same unknown entity seen
    # in multiple contexts). Semantic helps correlate description text.
    # Topology is weak because the node is not yet in the graph.

    "IDENTITY_MUTATION": WeightProfile(
        failure_mode="IDENTITY_MUTATION",
        w_sem=0.10, w_topo=0.15, w_temp=0.10, w_oper=0.20, w_ent=0.45,
    ),
    # Rationale: Identity mutations are CI naming changes.
    # Entity overlap is by far the strongest signal (old and new names
    # co-occur with the same operational context). Operational fingerprint
    # matters because mutations often correlate with change records.

    "PHANTOM_CI": WeightProfile(
        failure_mode="PHANTOM_CI",
        w_sem=0.20, w_topo=0.15, w_temp=0.10, w_oper=0.25, w_ent=0.30,
    ),
    # Rationale: Phantom CIs exist in CMDB but not in live telemetry.
    # Operational fingerprint is important (correlated maintenance windows).
    # Entity overlap and semantic content help group related phantom CIs.

    "DARK_ATTRIBUTE": WeightProfile(
        failure_mode="DARK_ATTRIBUTE",
        w_sem=0.25, w_topo=0.10, w_temp=0.10, w_oper=0.25, w_ent=0.30,
    ),
    # Rationale: Dark attributes are unexpected field values on known CIs.
    # Semantic similarity captures description correlation. Operational
    # fingerprint captures change-window and upgrade correlation. Entity
    # overlap ties together attributes on the same or related CIs.
}
```

**Changes from v2.0 profiles**:
- Added explicit temporal weight (`w_temp`) -- v2.0 applied temporal as a post-hoc modifier rather than a scored dimension.
- Added explicit entity overlap weight (`w_ent`) -- v2.0 had `w_entity` but did not include temporal as a dimension.
- All five weights sum to 1.0 per profile.
- Topological weight now represents true topological embedding similarity, not the `entity_overlap * 0.8` heuristic from v2.0 (remediates F-3.1).

### 6.3 Profile Validation Rules

At system startup, every profile MUST be validated:

1. All five weights are strictly positive: `w > 0.0`
2. All five weights sum to 1.0 within tolerance: `|sum - 1.0| < 1e-9`
3. `w_temp > 0.0` and `w_ent > 0.0` (guarantees `total_available > 0` in all mask states)

Validation failure prevents system startup with a clear error message identifying the invalid profile.

### 6.4 Validation Methodology (Tier 2: Outcome-Linked Calibration)

The initial weights are tagged as `calibration_status: "INITIAL_ESTIMATE"` in the snap decision record (Section 8). The methodology for empirical validation is:

**Phase 1 -- Baseline Collection** (passive, no weight changes):
1. Deploy with initial estimates.
2. Record all snap decisions with full per-dimension scores and the weights used.
3. Collect operator feedback on snap outcomes: TRUE_POSITIVE (correct snap), FALSE_POSITIVE (incorrect snap), FALSE_NEGATIVE (missed snap, discovered later).

**Phase 2 -- Sensitivity Analysis**:
1. For each profile, compute the marginal contribution of each dimension: how much does the final score change when each dimension's weight is perturbed by +/- 0.05?
2. Identify dimensions where the marginal contribution has high variance across TRUE_POSITIVE vs FALSE_POSITIVE cases. These are the dimensions where weight adjustment will have the most impact.

**Phase 3 -- Weight Optimization**:
1. Using collected (per-dimension scores, operator verdict) pairs, fit weights to maximize separation between TRUE_POSITIVE and FALSE_POSITIVE score distributions.
2. Optimization objective: maximize `AUC(final_score | operator_verdict)` per profile.
3. Constraint: all weights > 0.05, sum = 1.0.
4. Method: constrained Bayesian optimization or grid search over the 4-simplex (5 weights summing to 1.0).

**Phase 4 -- Deployment**:
1. Update profiles with optimized weights.
2. Tag `calibration_status: "EMPIRICALLY_VALIDATED"` with reference to the calibration dataset ID and date.
3. Continue collecting feedback for ongoing drift detection.

**Guardrails**:
- No weight may drop below 0.05 during optimization (prevents dimension exclusion by weight zeroing).
- Weight changes > 0.10 from baseline require review before deployment.
- Minimum 500 labeled outcomes per profile before optimization is attempted.

---

## 7. Composite Score Computation

### 7.1 Algorithm

Given fragments `A` and `B`, and weight profile `P`:

```
FUNCTION compute_composite_score(A, B, P):

    # Step 1: Determine availability
    avail = {}
    avail["semantic"]     = A.mask_semantic AND B.mask_semantic
    avail["topological"]  = A.mask_topological AND B.mask_topological
    avail["temporal"]     = TRUE
    avail["operational"]  = A.mask_operational AND B.mask_operational
    avail["entity_overlap"] = TRUE

    # Step 2: Compute per-dimension scores (only for available dimensions)
    scores = {}
    IF avail["semantic"]:
        scores["semantic"] = clamp(cosine(A.emb_semantic, B.emb_semantic), 0.0, 1.0)
    IF avail["topological"]:
        scores["topological"] = clamp(cosine(A.emb_topological, B.emb_topological), 0.0, 1.0)
    scores["temporal"] = clamp(cosine(A.emb_temporal, B.emb_temporal), 0.0, 1.0)
    IF avail["operational"]:
        scores["operational"] = clamp(cosine(A.emb_operational, B.emb_operational), 0.0, 1.0)
    scores["entity_overlap"] = jaccard(A.entities, B.entities)

    # Step 3: Redistribute weights
    base_weights = {
        "semantic": P.w_sem,  "topological": P.w_topo,
        "temporal": P.w_temp, "operational": P.w_oper,
        "entity_overlap": P.w_ent,
    }
    total_available = SUM(base_weights[d] for d in D_avail)
    # total_available > 0 guaranteed by temporal + entity_overlap always available

    adjusted_weights = {}
    FOR d IN D_avail:
        adjusted_weights[d] = base_weights[d] / total_available

    # Step 4: Weighted combination
    raw_composite = SUM(adjusted_weights[d] * scores[d] for d in D_avail)

    # Step 5: Defense-in-depth clamp (INV-3)
    final_score = clamp(raw_composite, 0.0, 1.0)

    RETURN final_score, scores, avail, adjusted_weights
```

### 7.2 Temporal Modifier

The v2.0 temporal modifier (Section that computes age decay, change proximity, and diurnal alignment) is **retained as a post-multiplication modifier** on the composite score. It is NOT part of the per-dimension scoring. The temporal embedding (`emb_temporal`) captures cyclical time features (time-of-day, day-of-week, month encoding) for pattern matching, while the temporal modifier captures the recency/freshness signal.

These are distinct signals:
- `S_temp` (temporal embedding cosine): "Do these two fragments occur at similar points in temporal cycles?"
- `temporal_modifier`: "How close in absolute time are these fragments, and does recency suggest they are part of the same incident?"

```
modulated_score = clamp(final_score * temporal_modifier, 0.0, 1.0)
```

The temporal modifier remains bounded to `[0.5, 1.0]` per the Audit 4.2 remediation. It can only attenuate, never amplify.

### 7.3 Determinism Guarantee

The scoring function is deterministic: given the same input fragment pair and weight profile, it always produces the same output score. This is guaranteed because:

1. All inputs are read from immutable database columns (embeddings and masks are write-once after enrichment).
2. `np.dot` and `np.linalg.norm` on `float64` arrays produce deterministic results on a single platform (IEEE 754).
3. No random number generation or non-deterministic operations.
4. The `clamp` function is a pure function.
5. Weight redistribution is a pure arithmetic function of the base weights and availability flags.

**Cross-platform note**: IEEE 754 float64 arithmetic may produce different results across CPU architectures for the same inputs due to extended-precision intermediate results. For cross-platform reproducibility, force `float64` dtype on all numpy operations (already specified in `_cosine_sim_clamped`). This is sufficient for scoring reproducibility within a single deployment.

---

## 8. Snap Decision Record

### 8.1 Structure

Every scored pair produces a `SnapDecisionRecord` that is persisted to the `snap_decision_log` table:

```python
@dataclass
class SnapDecisionRecord:
    # Identity
    tenant_id: str
    new_fragment_id: UUID
    candidate_fragment_id: UUID
    failure_mode_profile: str
    timestamp: datetime             # UTC, when scoring occurred

    # Per-dimension scores (None if dimension was unavailable)
    score_semantic: Optional[float]      # [0.0, 1.0] or None
    score_topological: Optional[float]   # [0.0, 1.0] or None
    score_temporal: float                # [0.0, 1.0] -- always available
    score_operational: Optional[float]   # [0.0, 1.0] or None
    score_entity_overlap: float          # [0.0, 1.0] -- always available

    # Dimension availability
    mask_semantic_available: bool
    mask_topological_available: bool
    mask_operational_available: bool
    # temporal and entity_overlap always True -- not stored, implied

    # Weights
    base_weights: dict[str, float]       # Original profile weights (5 keys, sum=1.0)
    adjusted_weights: dict[str, float]   # After redistribution (|D_avail| keys, sum=1.0)

    # Composite scoring
    raw_composite: float                 # [0.0, 1.0] -- weighted combination before temporal mod
    temporal_modifier: float             # [0.5, 1.0]
    final_score: float                   # [0.0, 1.0] -- raw_composite * temporal_modifier

    # Decision
    threshold_applied: float             # After Sidak correction
    decision: str                        # "SNAP" | "NEAR_MISS" | "AFFINITY" | "NONE"
    multiple_comparisons_k: int          # Number of profiles evaluated for this candidate

    # Calibration metadata
    calibration_status: str              # "INITIAL_ESTIMATE" | "EMPIRICALLY_VALIDATED"
    dimensions_available_count: int      # 2..5
```

### 8.2 Observability Properties

The decision record supports full post-hoc analysis:

1. **Reproducibility**: Given `base_weights`, `adjusted_weights`, and per-dimension scores, the `raw_composite` can be recomputed exactly.
2. **Mask auditing**: `mask_*_available` fields reveal how many decisions were made with degraded information. A high rate of `mask_semantic_available = FALSE` indicates LLM availability problems.
3. **Weight impact analysis**: Comparing `base_weights` to `adjusted_weights` shows how much redistribution occurred. Large redistribution indicates degraded scoring confidence.
4. **Calibration tracking**: `calibration_status` tags every decision with whether the weights were validated, enabling before/after analysis when weights are updated.
5. **Dimension contribution**: For each available dimension, `adjusted_weights[d] * score_d` gives the exact contribution to the composite score. This supports the Tier 2 sensitivity analysis (Section 6.4).

### 8.3 Storage Format

Per-dimension scores and weights are stored as JSONB columns for query flexibility:

```sql
component_scores JSONB NOT NULL,
-- Example: {
--   "score_semantic": 0.8234,
--   "score_topological": null,
--   "score_temporal": 0.6512,
--   "score_operational": 0.7891,
--   "score_entity_overlap": 0.4500
-- }

dimension_availability JSONB NOT NULL,
-- Example: {
--   "semantic": true,
--   "topological": false,
--   "operational": true
-- }

weights_base JSONB NOT NULL,
-- Example: {"w_sem": 0.15, "w_topo": 0.30, "w_temp": 0.10, "w_oper": 0.15, "w_ent": 0.30}

weights_adjusted JSONB NOT NULL,
-- Example: {"w_sem": 0.2143, "w_temp": 0.1429, "w_oper": 0.2143, "w_ent": 0.4286}
```

A `NULL` value in `component_scores` for a dimension means the dimension was unavailable (mask=FALSE for at least one fragment in the pair). This is distinct from a score of `0.0` (which means the dimension was available but the fragments had zero similarity).

---

## 9. Implementation Pseudocode

Complete scoring function suitable for direct translation to Python:

```python
import numpy as np
from dataclasses import dataclass
from typing import Optional
from uuid import UUID
from datetime import datetime

EPSILON = 1e-10


def _cosine_sim_clamped(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity clamped to [0.0, 1.0]."""
    a64 = np.asarray(a, dtype=np.float64)
    b64 = np.asarray(b, dtype=np.float64)
    norm_a = np.linalg.norm(a64)
    norm_b = np.linalg.norm(b64)
    if norm_a < EPSILON or norm_b < EPSILON:
        return 0.0
    raw = float(np.dot(a64, b64) / (norm_a * norm_b))
    return max(0.0, min(1.0, raw))


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity in [0.0, 1.0]."""
    if not set_a and not set_b:
        return 0.0
    union_size = len(set_a | set_b)
    if union_size == 0:
        return 0.0
    return len(set_a & set_b) / union_size


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def score_pair_v3(
    frag_a,   # AbeyanceFragmentORM
    frag_b,   # AbeyanceFragmentORM
    entities_a: set[str],
    entities_b: set[str],
    profile: WeightProfile,
    temporal_modifier: float,  # [0.5, 1.0] from _compute_temporal_modifier
) -> SnapDecisionRecord:
    """
    Per-dimension scoring with mask-aware weight redistribution.

    Returns a fully populated SnapDecisionRecord.
    """

    # --- Step 1: Determine dimension availability ---
    avail_sem  = bool(frag_a.mask_semantic and frag_b.mask_semantic)
    avail_topo = bool(frag_a.mask_topological and frag_b.mask_topological)
    avail_oper = bool(frag_a.mask_operational and frag_b.mask_operational)
    # temporal and entity_overlap: always available

    # --- Step 2: Compute per-dimension scores ---
    score_sem:  Optional[float] = None
    score_topo: Optional[float] = None
    score_oper: Optional[float] = None

    if avail_sem:
        score_sem = _cosine_sim_clamped(frag_a.emb_semantic, frag_b.emb_semantic)
    if avail_topo:
        score_topo = _cosine_sim_clamped(frag_a.emb_topological, frag_b.emb_topological)
    score_temp: float = _cosine_sim_clamped(frag_a.emb_temporal, frag_b.emb_temporal)
    if avail_oper:
        score_oper = _cosine_sim_clamped(frag_a.emb_operational, frag_b.emb_operational)
    score_ent: float = _jaccard(entities_a, entities_b)

    # --- Step 3: Weight redistribution ---
    base_w = {
        "semantic": profile.w_sem,
        "topological": profile.w_topo,
        "temporal": profile.w_temp,
        "operational": profile.w_oper,
        "entity_overlap": profile.w_ent,
    }

    avail_flags = {
        "semantic": avail_sem,
        "topological": avail_topo,
        "temporal": True,
        "operational": avail_oper,
        "entity_overlap": True,
    }

    total_available = sum(
        base_w[d] for d, is_avail in avail_flags.items() if is_avail
    )
    # total_available > 0 guaranteed: temporal + entity_overlap always available,
    # both have strictly positive weights (enforced by profile validation).

    adjusted_w = {}
    for d, is_avail in avail_flags.items():
        if is_avail:
            adjusted_w[d] = base_w[d] / total_available

    # --- Step 4: Weighted combination ---
    dim_scores = {
        "semantic": score_sem,
        "topological": score_topo,
        "temporal": score_temp,
        "operational": score_oper,
        "entity_overlap": score_ent,
    }

    raw_composite = 0.0
    for d, w in adjusted_w.items():
        raw_composite += w * dim_scores[d]

    raw_composite = _clamp(raw_composite, 0.0, 1.0)

    # --- Step 5: Apply temporal modifier ---
    final_score = _clamp(raw_composite * temporal_modifier, 0.0, 1.0)

    # --- Step 6: Build decision record ---
    dims_available = sum(1 for v in avail_flags.values() if v)

    return SnapDecisionRecord(
        score_semantic=score_sem,
        score_topological=score_topo,
        score_temporal=score_temp,
        score_operational=score_oper,
        score_entity_overlap=score_ent,
        mask_semantic_available=avail_sem,
        mask_topological_available=avail_topo,
        mask_operational_available=avail_oper,
        base_weights=base_w,
        adjusted_weights=adjusted_w,
        raw_composite=round(raw_composite, 6),
        temporal_modifier=round(temporal_modifier, 6),
        final_score=round(final_score, 6),
        calibration_status="INITIAL_ESTIMATE",
        dimensions_available_count=dims_available,
        # remaining fields (identity, decision, threshold) filled by caller
    )
```

---

## 10. Rounding and Precision

All stored scores are rounded to 6 decimal places (`round(x, 6)`). This provides:

- Sufficient precision for threshold comparisons (thresholds are specified to 2 decimal places).
- Deterministic string representation for logging and debugging.
- Avoidance of spurious floating-point differences in equality comparisons.

Internal computation uses `float64` throughout. Rounding is applied only at the persistence boundary (when writing to the `SnapDecisionRecord`).

---

## 11. Interaction with Existing Subsystems

### 11.1 Temporal Modifier (retained)

The `_compute_temporal_modifier()` function from v2.0 is retained unchanged. It produces a value in `[0.5, 1.0]` that modulates the composite score. This is a deliberate architectural choice: the temporal modifier captures absolute-time recency, while `S_temp` (temporal embedding cosine) captures cyclical temporal pattern similarity. These are orthogonal signals.

### 11.2 Sidak Correction (retained)

The multiple-comparisons correction via `_sidak_threshold()` is retained. When multiple failure mode profiles are evaluated for the same candidate pair, the snap threshold is adjusted upward per the Sidak formula. The `multiple_comparisons_k` field in the decision record tracks this.

### 11.3 Targeted Retrieval (unchanged)

The entity-overlap-based retrieval in `_targeted_retrieval()` is unchanged. It produces candidate fragments; the scoring redesign affects only how candidates are scored after retrieval.

### 11.4 Accumulation Graph (interface stable)

The accumulation graph receives `(fragment_a_id, fragment_b_id, affinity_score, failure_mode)` from snap decisions. The affinity_score is now the `final_score` from the per-dimension scoring. The interface is unchanged.

---

## 12. Migration from v2.0

### 12.1 Schema Changes Required (specified elsewhere)

The v3.0 schema replaces the single `enriched_embedding Vector(1536)` column with four separate embedding columns and three boolean mask columns. This schema change is specified in the schema design task (T1.2), not here.

### 12.2 Scoring Compatibility

v2.0 fragments (with single concatenated embedding) cannot be scored by the v3.0 per-dimension scoring engine. During migration:

1. Fragments that have not yet been scored retain their v2.0 scores.
2. New fragments are scored with v3.0.
3. Re-scoring of v2.0 fragments requires re-enrichment (re-running the enrichment chain to produce separate embeddings). This is a batch migration task.

### 12.3 Weight Profile Migration

The v2.0 4-weight profiles (`w_sem, w_topo, w_entity, w_oper`) are replaced by v3.0 5-weight profiles (`w_sem, w_topo, w_temp, w_oper, w_ent`). The temporal weight is carved from the other four weights (not added on top). All v3.0 profiles sum to 1.0.

---

## 13. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-3 | All scores in `[0.0, 1.0]` | `_clamp()` on every per-dimension score and final composite |
| INV-8 | No output outside declared range | `_clamp()` defense-in-depth on `final_score` |
| INV-10 | All scoring decisions persisted | `SnapDecisionRecord` written for every evaluated pair |
| INV-11 | Mask vector consulted during scoring | `available_d(A,B)` checked before every cosine computation |
| INV-13 | Multiple comparisons corrected | Sidak correction applied to thresholds |
| INV-NEW-1 | Available weight sum > 0 | Temporal + entity_overlap always available; weights strictly positive |
| INV-NEW-2 | Adjusted weights sum to 1.0 | Redistribution formula guarantees this algebraically |
| INV-NEW-3 | No cosine on NULL embeddings | Availability predicate prevents computation on unavailable dimensions |
