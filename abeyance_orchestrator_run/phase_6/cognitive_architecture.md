# Abeyance Memory v3.0 -- Cognitive Architecture Layers

**Task**: Phase 6 -- Cognitive Architecture Design
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Inputs**: Phase 1 (T1.1-T1.4), Phase 3 (D1.1, T3.1, T3.3, T3.1-Bridge), Phase 4 (D2.1, D2.1-Conflict, D2.1-Temporal), Phase 5 (D3.8, T5.2, D3.1, D11.1, D4.1, T4.2, D14.1)

---

## 1. Five-Layer Architecture

The cognitive architecture organises all 14 discovery mechanisms plus the foundational enrichment/scoring infrastructure into five layers. Each layer has a defined responsibility, a strict dependency contract (reads only from lower layers), and a defined output contract (writes to its own tables, never mutates lower-layer tables).

```
+===============================================================+
| LAYER 5: INSIGHT                                              |
|   (13) Meta-Memory    (14) Evolutionary Patterns              |
|   Output: exploration bias, pattern fitness trajectories      |
+===============================================================+
        ^  reads: Evidence layer outputs, Hypothesis outcomes
+===============================================================+
| LAYER 4: EVIDENCE                                             |
|   (11) Pattern Compression  (12) Counterfactual Simulation    |
|   Output: compression rules, causal impact deltas             |
+===============================================================+
        ^  reads: Hypothesis layer outputs, Discovery/Correlation
+===============================================================+
| LAYER 3: HYPOTHESIS                                           |
|   (8) Hypothesis Generation   (9) Expectation Violation       |
|   (10) Causal Direction                                       |
|   Output: falsifiable claims, violation records, causal cands |
+===============================================================+
        ^  reads: Discovery layer outputs, Correlation tables
+===============================================================+
| LAYER 2: DISCOVERY                                            |
|   (1) Surprise Metrics   (2) Ignorance Mapping               |
|   (3) Negative Evidence  (4) Bridge Detection                 |
|   (5) Outcome Calibration  (6) Pattern Conflict               |
|   (7) Temporal Sequence                                       |
|   Output: surprise events, ignorance maps, disconfirmation    |
|           records, bridge discoveries, calibration history,   |
|           conflict records, sequence logs & transition mats   |
+===============================================================+
        ^  reads: Correlation layer tables
+===============================================================+
| LAYER 1: CORRELATION (Foundation)                             |
|   Enrichment Chain (T1.3) | Snap Engine (T1.4)               |
|   Model Serving (T1.1)    | ORM Schema (T1.2)                |
|   Output: fragments, embeddings, snap decisions, accum edges  |
+===============================================================+
```

---

## 2. Layer Definitions

### 2.1 Layer 1: Correlation (Foundation)

**Responsibility**: Ingest raw evidence, enrich with embeddings, score pairwise fragment similarity, maintain the accumulation graph.

**Components**:
- T1.1 -- T-VEC / TSLAM Serving Architecture (model loading, batching, resource isolation)
- T1.2 -- ORM Schema (abeyance_fragment, cold_fragment, snap_decision_record)
- T1.3 -- Enrichment Chain (entity extraction, 4-column embedding generation)
- T1.4 -- Snap Engine Scoring (per-dimension scoring, mask-aware weight redistribution)

**Tables owned**:

| Table | Purpose | Key Columns |
|---|---|---|
| `abeyance_fragment` | Active fragment storage | id, tenant_id, emb_semantic, emb_topological, emb_temporal, emb_operational, mask_* |
| `cold_fragment` | Archived fragment ANN storage | original_fragment_id, tenant_id, emb_*, mask_* |
| `snap_decision_record` | Per-pair scoring audit log | new_fragment_id, candidate_fragment_id, score_*, final_score, decision |
| `fragment_entity_ref` | Fragment-to-entity linkage | fragment_id, entity_id, entity_identifier |
| `accumulation_edge` | Affinity graph edges | fragment_a_id, fragment_b_id, affinity_score |
| `fragment_history` | Fragment lifecycle audit | fragment_id, event_type |
| `shadow_entity` | Entity identity registry | id, tenant_id, entity_identifier, entity_domain |
| `shadow_relationship` | Entity-to-entity topology | from_entity_id, to_entity_id, type |
| `cluster_snapshot` | Cluster detection results | cluster_id, fragment_ids |
| `discovery_ledger` | Cross-layer event log | event_type, source_mechanism |

**Dependency**: None (foundation layer).

**Tenant isolation**: `tenant_id` on every table. Every query includes `tenant_id` in WHERE clause. Every index has `tenant_id` as leading column.

---

### 2.2 Layer 2: Discovery

**Responsibility**: Observe the outputs of Layer 1 and detect anomalies, gaps, conflicts, bridges, and temporal structure. Discovery mechanisms are passive observers that never modify Layer 1 tables.

**Components and mechanism mapping**:

| # | Mechanism | Tier | Layer | Reads From | Writes To |
|---|---|---|---|---|---|
| 1 | Surprise Metrics | 1 | Discovery | `snap_decision_record` | `surprise_event`, `surprise_distribution_state` |
| 2 | Ignorance Mapping | 1 | Discovery | `abeyance_fragment`, `cold_fragment`, `snap_decision_record` | `ignorance_extraction_stat`, `ignorance_mask_distribution`, `ignorance_silent_decay_record`, `ignorance_silent_decay_stat`, `ignorance_map_entry`, `exploration_directive`, `ignorance_job_run` |
| 3 | Negative Evidence | 1 | Discovery | `abeyance_fragment`, `accumulation_edge` | `disconfirmation_events`, `disconfirmation_fragments`, `disconfirmation_patterns` |
| 4 | Bridge Detection | 1 | Discovery | `accumulation_edge`, `fragment_entity_ref` | `bridge_discovery`, `bridge_discovery_provenance` |
| 5 | Outcome Calibration | 2 | Discovery | `snap_decision_record` | `snap_outcome_feedback`, `calibration_history`, `weight_profile_active` |
| 6 | Pattern Conflict | 2 | Discovery | `snap_decision_record`, `abeyance_fragment` | `conflict_record`, `conflict_detection_log` |
| 7 | Temporal Sequence | 2 | Discovery | `abeyance_fragment`, `fragment_entity_ref`, `shadow_entity` | `entity_sequence_log`, `transition_matrix`, `transition_matrix_version` |

**Rationale for placing all seven mechanisms in Layer 2 (Discovery)**:

Tier 1 and Tier 2 mechanisms share a fundamental property: they observe Layer 1 outputs and produce structured discovery signals without generating reasoning artefacts (hypotheses, causal claims). They differ in data requirements (Tier 1 needs no operator feedback; Tier 2 needs operator actions or temporal accumulation) but not in architectural role. Splitting them across layers would create a false distinction that complicates data flow. Within Layer 2, tier ordering governs startup dependencies (Tier 2 mechanisms may read Tier 1 outputs within the same layer), but all seven write to the same architectural stratum.

**Internal tier dependency within Layer 2**:
```
Tier 2 mechanisms (5, 6, 7) MAY read Tier 1 outputs (1, 2, 3, 4)
Tier 1 mechanisms (1, 2, 3, 4) MUST NOT read Tier 2 outputs
```

**Tenant isolation**: All Discovery tables include `tenant_id`. `surprise_event`, `ignorance_map_entry`, `conflict_record`, `entity_sequence_log`, `transition_matrix` all have `tenant_id` as the first column of their primary key or leading index.

---

### 2.3 Layer 3: Hypothesis

**Responsibility**: Generate falsifiable claims, detect expectation violations, and test causal direction. This layer produces reasoning artefacts that require LLM inference (Hypothesis Generation) or statistical testing (Expectation Violation, Causal Direction).

**Components and mechanism mapping**:

| # | Mechanism | Tier | Layer | Reads From | Writes To |
|---|---|---|---|---|---|
| 8 | Hypothesis Generation | 3 | Hypothesis | `surprise_event`, `accumulation_edge`, `cluster_snapshot`, `snap_decision_record` | `hypothesis`, `hypothesis_evidence`, `hypothesis_generation_queue` |
| 9 | Expectation Violation | 3 | Hypothesis | `entity_sequence_log`, `transition_matrix`, `surprise_event` | `expectation_violation` |
| 10 | Causal Direction | 3 | Hypothesis | `entity_sequence_log`, `shadow_entity`, `fragment_entity_ref` | `causal_candidate`, `causal_evidence_pair`, `causal_analysis_run` |

**Cross-layer reads**:
- Mechanism 8 reads Layer 1 (`snap_decision_record`, `accumulation_edge`) and Layer 2 (`surprise_event`).
- Mechanism 9 reads Layer 2 (`entity_sequence_log`, `transition_matrix`) and Layer 2 (`surprise_event` for Laplace smoothing convention).
- Mechanism 10 reads Layer 2 (`entity_sequence_log`) and Layer 1 (`shadow_entity`, `fragment_entity_ref`).

**No upward reads**: Hypothesis layer never reads from Evidence or Insight layers.

**Tenant isolation**: `hypothesis.tenant_id`, `expectation_violation.tenant_id`, `causal_candidate.tenant_id` on all tables. `causal_analysis_run` scoped to single tenant per run.

---

### 2.4 Layer 4: Evidence

**Responsibility**: Validate patterns through compression analysis and counterfactual simulation. These mechanisms operate on populations of snap decisions and hypothesis outputs to produce evidence that either strengthens or weakens claims from lower layers.

**Components and mechanism mapping**:

| # | Mechanism | Tier | Layer | Reads From | Writes To |
|---|---|---|---|---|---|
| 11 | Pattern Compression | 4 | Evidence | `snap_decision_record`, `surprise_event` | `compression_discovery_event` |
| 12 | Counterfactual Simulation | 4 | Evidence | `snap_decision_record`, `abeyance_fragment`, `entity_sequence_log` | `counterfactual_simulation_result`, `counterfactual_pair_delta`, `counterfactual_candidate_queue`, `counterfactual_job_run` |

**Cross-layer reads**:
- Mechanism 11 reads Layer 1 (`snap_decision_record`) and Layer 2 (`surprise_event`).
- Mechanism 12 reads Layer 1 (`snap_decision_record`, `abeyance_fragment`) and Layer 2 (`entity_sequence_log`).

**Operational constraint**: Both mechanisms are batch-only. Mechanism 12 (Counterfactual Simulation) runs exclusively in maintenance windows with read-only database sessions against production tables.

**Tenant isolation**: Both mechanisms are scoped per `(tenant_id, failure_mode_profile)`. `compression_discovery_event.tenant_id` and all counterfactual tables include `tenant_id`.

---

### 2.5 Layer 5: Insight

**Responsibility**: Learn from the full history of discovery, hypothesis, and evidence outcomes. Produce long-term strategic signals: where to focus exploration (Meta-Memory) and how patterns evolve over time (Evolutionary Patterns).

**Components and mechanism mapping**:

| # | Mechanism | Tier | Layer | Reads From | Writes To |
|---|---|---|---|---|---|
| 13 | Meta-Memory | 4 | Insight | `snap_outcome_feedback`, `snap_decision_record`, `ignorance_map_entry`, `exploration_directive` | `meta_memory_area`, `meta_memory_productivity`, `meta_memory_bias`, `meta_memory_topological_region`, `meta_memory_tenant_state`, `meta_memory_job_run` |
| 14 | Evolutionary Patterns | 4 | Insight | `snap_outcome_feedback`, `snap_decision_record`, `surprise_event`, `compression_discovery_event` | `pattern_individual`, `pattern_individual_archive`, `evolution_generation_log`, `evolution_partition_state` |

**Cross-layer reads**:
- Mechanism 13 reads Layer 1 (`snap_decision_record`), Layer 2 (`snap_outcome_feedback`, `ignorance_map_entry`, `exploration_directive`).
- Mechanism 14 reads Layer 1 (`snap_decision_record`), Layer 2 (`snap_outcome_feedback`, `surprise_event`), and Layer 4 (`compression_discovery_event`).

**Rationale for placing Meta-Memory and Evolutionary Patterns in Insight rather than Evidence**:

Both mechanisms are meta-layers that operate on the *outcomes* of the discovery/evidence pipeline, not on raw snap decisions. Meta-Memory tracks productivity across search areas using operator feedback labels. Evolutionary Patterns tracks pattern fitness using compression gain, surprise novelty, and predictive power -- all outputs of lower layers. Neither mechanism produces evidence that could confirm or refute a specific hypothesis. They produce strategic guidance: "search here more" (Meta-Memory) and "this pattern is strengthening" (Evolutionary Patterns). This is qualitatively different from the Evidence layer's role of validating specific claims.

**Tenant isolation**: All six meta_memory_* tables and all four evolution_* tables include `tenant_id` as a leading column.

---

## 3. Data Flow Between Layers

### 3.1 Primary Data Flow (Hot Path)

```
Raw Event
  |
  v
[Layer 1: Correlation]
  EnrichmentChain.enrich()
    -> AbeyanceFragmentORM (4 embeddings + masks)
    -> FragmentEntityRefORM entries
    -> SnapEngine.evaluate()
      -> SnapDecisionRecord (per-dimension scores)
      -> AccumulationEdge (affinity graph)
  |
  v
[Layer 2: Discovery] -- triggered inline or near-real-time
  SurpriseEngine.process(snap_decision_record)
    -> SurpriseEvent (if surprise > adaptive_threshold)
  TemporalSequence.record_observation(fragment, entity_refs)
    -> entity_sequence_log entries
    -> transition_matrix incremental update
  ConflictDetector.evaluate(snap_decision_record)
    -> conflict_record (if opposite polarity detected)
  BridgeDetector.analyze(accumulation_graph_component)
    -> bridge_discovery (if articulation point + cross-domain)
  |
  v
[Layer 3: Hypothesis] -- near-real-time or scheduled
  ViolationDetector.evaluate_transition(entity, S_prev, S_new)
    -> expectation_violation (if severity > threshold)
  HypothesisEngine.generate(surprise_event | cluster_change)
    -> hypothesis (TSLAM-8B falsifiable claim)
  CausalDirection.analyze(entity_pair)
    -> causal_candidate (if consistent temporal ordering)
  |
  v
[Layer 4: Evidence] -- batch only
  PatternCompression.compress(snap_decision_population)
    -> compression_discovery_event
  CounterfactualSimulation.simulate(candidate_fragment, window)
    -> counterfactual_simulation_result + pair_deltas
  |
  v
[Layer 5: Insight] -- batch, slow cycle
  MetaMemory.compute_productivity(search_areas, outcomes)
    -> meta_memory_bias (exploration allocation)
  EvolutionaryPatterns.evolve(pattern_population)
    -> pattern_individual fitness updates, selection, recombination
```

### 3.2 Feedback Loops

Two feedback loops cross layer boundaries downward:

**Loop A -- Weight Calibration** (Layer 2 -> Layer 1):
```
snap_decision_record (L1) -> snap_outcome_feedback (L2) -> calibration_history (L2)
  -> weight_profile_active (L2) -> SnapEngine reads updated weights (L1)
```
The snap engine reads `weight_profile_active` at each scoring cycle. Outcome Calibration (Mechanism 5) writes to this table. This is the only case where a Discovery-layer output directly influences Correlation-layer behaviour. The feedback is mediated through a registry table, not through direct mutation of snap logic.

**Loop B -- Exploration Bias** (Layer 5 -> Layer 1):
```
snap_outcome_feedback (L2) + ignorance_map_entry (L2)
  -> meta_memory_bias (L5) -> SnapEngine candidate generation priority (L1)
```
Meta-Memory (Mechanism 13) produces exploration biases that influence which fragment pairs the snap engine prioritises for evaluation. This is a soft bias (priority ordering), not a hard filter. The snap engine can still evaluate any pair; Meta-Memory only reorders the candidate list.

**Both feedback loops are unidirectional and mediated through registry tables. No mechanism directly calls into or mutates another mechanism's internal state.**

### 3.3 Dependency Matrix

```
                     Reads From Layer:
Mechanism            L1    L2    L3    L4    L5
-------------------------------------------------
L1: Enrichment       -     -     -     -     -
L1: Snap Engine      -     [A]   -     -     [B]
L2: 1-Surprise       R     -     -     -     -
L2: 2-Ignorance      R     -     -     -     -
L2: 3-NegEvidence    R     -     -     -     -
L2: 4-Bridge         R     -     -     -     -
L2: 5-Calibration    R     -     -     -     -
L2: 6-Conflict       R     -     -     -     -
L2: 7-TempSequence   R     -     -     -     -
L3: 8-Hypothesis     R     R     -     -     -
L3: 9-ExpViolation   -     R     -     -     -
L3: 10-CausalDir     R     R     -     -     -
L4: 11-Compression   R     R     -     -     -
L4: 12-Counterfact   R     R     -     -     -
L5: 13-MetaMemory    R     R     -     -     -
L5: 14-Evolutionary  R     R     -     R     -

[A] = feedback loop A (weight calibration)
[B] = feedback loop B (exploration bias)
R   = read dependency
```

**Key property**: No mechanism reads from its own layer or from a higher layer (except the two explicit feedback loops, which are mediated through registry tables and documented above). This prevents circular dependencies.

---

## 4. Tier-to-Layer Mapping

The 14 mechanisms span 4 implementation tiers (based on dependency complexity) mapped to 5 architectural layers (based on cognitive function):

| Tier | Mechanisms | Layer Assignment |
|---|---|---|
| 1 (Foundation) | 1-Surprise, 2-Ignorance, 3-NegEvidence, 4-Bridge | Layer 2: Discovery |
| 2 (Feedback Loop) | 5-Calibration, 6-Conflict, 7-TempSequence | Layer 2: Discovery |
| 3 (Reasoning) | 8-Hypothesis, 9-ExpViolation, 10-CausalDirection | Layer 3: Hypothesis |
| 4 (Advanced) | 11-Compression, 12-Counterfactual | Layer 4: Evidence |
| 4 (Advanced) | 13-MetaMemory, 14-Evolutionary | Layer 5: Insight |

**Tier 4 splits across two layers.** Tier 4 contains four mechanisms with two distinct cognitive roles:
- Mechanisms 11-12 validate specific patterns (Evidence function).
- Mechanisms 13-14 learn strategic guidance from historical outcomes (Insight function).

The tier number reflects implementation ordering (all require Tiers 1-3 stable). The layer reflects cognitive role. These are orthogonal classifications; tiers govern build order, layers govern data flow.

---

## 5. Conflicts Identified and Resolved

### 5.1 CONFLICT: snap_decision_record vs snap_decision_log

**Description**: The snap decision table is named inconsistently across specifications.

| Specification | Name Used |
|---|---|
| Phase 1: orm_schema.md (T1.2) | `snap_decision_record` |
| Phase 1: snap_scoring.md (T1.4) | `snap_decision_log` (in SnapDecisionRecord dataclass, Section 8.3 shows `component_scores JSONB`) |
| Phase 3: ignorance_mapping.md | `snap_decision_record` |
| Phase 4: conflict_detection.md | `snap_decision_record` |
| Phase 4: outcome_calibration.md | `snap_decision_record` |
| Phase 5: hypothesis_engine.md | `snap_decision_log` |
| Phase 5: counterfactual_simulation.md | `snap_decision_log` |
| Phase 5: pattern_compression.md | `snap_decision_log` |
| Phase 5: evolutionary_patterns.md | `snap_decision_log` |
| Phase 5: meta_memory.md | `snap_decision_record` |

**Resolution**: The canonical name is **`snap_decision_record`** as defined in the ORM schema (T1.2), which is the authoritative source for table names. The Phase 5 specifications (hypothesis_engine, counterfactual_simulation, pattern_compression, evolutionary_patterns) that use `snap_decision_log` MUST be corrected to `snap_decision_record`. The ORM defines `ActiveFragmentORM` mapping to `abeyance_fragment` and the snap record table as `snap_decision_record`. The `_record` suffix is consistent with the append-only audit log semantics (INV-10).

**Impact**: All SQL queries in Phase 5 specs referencing `snap_decision_log` must be updated. No schema change required; the table already exists as `snap_decision_record`.

---

### 5.2 CONFLICT: snap_scoring.md Section 8.3 JSONB vs orm_schema.md typed columns

**Description**: The snap scoring spec (T1.4) Section 8.3 describes storing per-dimension scores in a `component_scores JSONB` column and weights in `weights_base JSONB` / `weights_adjusted JSONB` columns. The ORM schema (T1.2) defines explicit typed columns: `score_semantic FLOAT`, `score_topological FLOAT`, `score_temporal FLOAT`, `score_operational FLOAT`, `score_entity_overlap FLOAT`, `masks_active JSONB`, `weights_used JSONB`.

| Field | snap_scoring.md (T1.4) | orm_schema.md (T1.2) |
|---|---|---|
| Per-dimension scores | `component_scores JSONB` | Five explicit FLOAT columns |
| Availability | `dimension_availability JSONB` | `masks_active JSONB` |
| Base weights | `weights_base JSONB` | Not present (only `weights_used`) |
| Adjusted weights | `weights_adjusted JSONB` | `weights_used JSONB` |

**Resolution**: The ORM schema (T1.2) takes precedence for physical table layout because it is the authoritative schema definition that Alembic migrations are generated from. The explicit typed columns (`score_semantic`, `score_topological`, etc.) are superior to JSONB for query performance, type safety, and NULL semantics (a NULL FLOAT column is semantically "dimension unavailable" vs a JSONB key-miss which requires application-layer interpretation).

**Reconciled schema for `snap_decision_record`**:
- Per-dimension scores: five explicit FLOAT columns (`score_semantic`, `score_topological`, `score_temporal`, `score_operational`, `score_entity_overlap`) per T1.2.
- Availability: `masks_active JSONB` per T1.2. Contains `{"semantic": true, "topological": false, ...}`.
- Weights used: `weights_used JSONB` per T1.2. Contains the adjusted (post-redistribution) weights.
- Base weights: **ADD** `weights_base JSONB` from T1.4 to the schema. This is needed for the Outcome Calibration (Mechanism 5) sensitivity analysis, which must know the original profile weights, not just the adjusted weights. The ORM schema should be updated in a follow-up revision.

**Impact**: T1.2 requires a minor additive change (add `weights_base JSONB`). T1.4 Section 8.3 must be updated to reference the five typed columns instead of `component_scores JSONB`.

---

### 5.3 CONFLICT: Outcome Calibration writes weight_profile_active (Layer 2 -> Layer 1 feedback)

**Description**: Outcome Calibration (Mechanism 5, Layer 2) writes to `weight_profile_active`, which the Snap Engine (Layer 1) reads. This is a downward write that violates the "layers write only to their own tables" principle.

**Resolution**: This is an intentional, documented feedback loop (Section 3.2, Loop A). `weight_profile_active` is architecturally a **registry table** owned by Layer 2, not by Layer 1. The Snap Engine reads it but does not write to it. The enrichment chain and snap engine have no write path to this table. This is analogous to a configuration table: Layer 2 publishes configuration that Layer 1 consumes. The dependency is unidirectional and mediated.

**Formal rule**: `weight_profile_active` is owned by Layer 2 (Outcome Calibration). Layer 1 has READ-ONLY access.

---

### 5.4 CONFLICT: Disconfirmation table naming inconsistency

**Description**: The Negative Evidence spec (T3.3) describes `DisconfirmationRecord` as a dataclass but defines three physical tables: `disconfirmation_events`, `disconfirmation_fragments`, `disconfirmation_patterns`. The text in Section 2.2 refers to "identical `DisconfirmationRecord` entries" suggesting a single table, but the schema defines three.

**Resolution**: The three-table design is correct and preferred. `disconfirmation_events` is the event-level record (who, when, why). `disconfirmation_fragments` is the join table linking events to the specific fragment IDs being disconfirmed. `disconfirmation_patterns` stores the propagation pattern for future score penalties. The `DisconfirmationRecord` dataclass is the application-layer object that spans all three tables. The text in Section 2.2 should be read as "produce identical application-layer records" not "write to a single table."

---

### 5.5 CONFLICT: Hypothesis engine references snap_decision_log in source_table field

**Description**: The hypothesis engine spec defines `EvidenceRecord.source_table` as a string containing the table name of the evidence source. It gives the example `snap_decision_log`. This must be `snap_decision_record` per Conflict 5.1.

**Resolution**: Subsumed by Conflict 5.1. All `source_table` string values referencing the snap decision table must use `snap_decision_record`.

---

### 5.6 CONFLICT: Evolutionary Patterns reads snap_decision_log (Phase 5 spec) but also references snap_outcome_feedback (Phase 4 spec)

**Description**: The Evolutionary Patterns spec references both `snap_decision_log` (wrong name, per 5.1) and `snap_outcome_feedback` from Phase 4. It computes predictive power by joining snap decisions to outcome feedback. The join key is `snap_decision_record.id = snap_outcome_feedback.snap_decision_record_id`, which is consistent with the Phase 4 schema. The naming conflict is purely the `_log` vs `_record` issue.

**Resolution**: Subsumed by Conflict 5.1. No structural issue; only the table name string needs correction.

---

### 5.7 OBSERVATION: Consistent tenant isolation across all mechanisms

**Verification**: Every table defined across all 14 mechanism specifications includes `tenant_id` as a NOT NULL column. Every query example includes `WHERE tenant_id = :tenant_id`. Every index definition has `tenant_id` as the first or leading column. The temporal sequence `entity_sequence_log` partitioning scheme uses `(tenant_id, event_timestamp)` as the partition key.

**Result**: No conflict. Tenant isolation pattern (INV-7) is consistently applied across all specifications.

---

### 5.8 OBSERVATION: Consistent embedding mask handling

**Verification**: All mechanisms that read fragment embeddings check mask columns before computing similarity. The Surprise Engine operates on composite `final_score` (post-mask-redistribution), not on raw embeddings. Ignorance Mapping reads masks to compute ignorance scores. Pattern Compression discretizes per-dimension scores, using `X` band for NULL/masked dimensions.

**Result**: No conflict. The mask-aware scoring invariant (INV-11) is respected throughout.

---

## 6. Complete Table Registry

All tables, grouped by owning layer:

### Layer 1: Correlation

| Table | Owner | Inherited from v2 | New in v3 |
|---|---|---|---|
| `abeyance_fragment` | T1.2 | Yes (modified) | 4 embedding + 3 mask columns |
| `cold_fragment` | T1.2 | Yes (modified) | 4 embedding + 3 mask columns |
| `snap_decision_record` | T1.2 | Yes (modified) | 5 explicit score columns, masks_active, weights_used |
| `fragment_entity_ref` | v2.0 | Yes | No changes |
| `accumulation_edge` | v2.0 | Yes | No changes |
| `fragment_history` | v2.0 | Yes | No changes |
| `cluster_snapshot` | v2.0 | Yes | No changes |
| `shadow_entity` | v2.0 | Yes | No changes |
| `shadow_relationship` | v2.0 | Yes | No changes |
| `cmdb_export_log` | v2.0 | Yes | No changes |
| `discovery_ledger` | v2.0 | Yes | No changes |
| `value_event` | v2.0 | Yes | No changes |

### Layer 2: Discovery

| Table | Owner Mechanism | New in v3 |
|---|---|---|
| `surprise_event` | #1 Surprise Metrics | Yes |
| `surprise_distribution_state` | #1 Surprise Metrics | Yes |
| `ignorance_extraction_stat` | #2 Ignorance Mapping | Yes |
| `ignorance_mask_distribution` | #2 Ignorance Mapping | Yes |
| `ignorance_silent_decay_record` | #2 Ignorance Mapping | Yes |
| `ignorance_silent_decay_stat` | #2 Ignorance Mapping | Yes |
| `ignorance_map_entry` | #2 Ignorance Mapping | Yes |
| `exploration_directive` | #2 Ignorance Mapping | Yes |
| `ignorance_job_run` | #2 Ignorance Mapping | Yes |
| `disconfirmation_events` | #3 Negative Evidence | Yes |
| `disconfirmation_fragments` | #3 Negative Evidence | Yes |
| `disconfirmation_patterns` | #3 Negative Evidence | Yes |
| `bridge_discovery` | #4 Bridge Detection | Yes |
| `bridge_discovery_provenance` | #4 Bridge Detection | Yes |
| `snap_outcome_feedback` | #5 Outcome Calibration | Yes |
| `calibration_history` | #5 Outcome Calibration | Yes |
| `weight_profile_active` | #5 Outcome Calibration | Yes |
| `conflict_record` | #6 Pattern Conflict | Yes |
| `conflict_detection_log` | #6 Pattern Conflict | Yes |
| `entity_sequence_log` | #7 Temporal Sequence | Yes |
| `transition_matrix` | #7 Temporal Sequence | Yes |
| `transition_matrix_version` | #7 Temporal Sequence | Yes |

### Layer 3: Hypothesis

| Table | Owner Mechanism | New in v3 |
|---|---|---|
| `hypothesis` | #8 Hypothesis Generation | Yes |
| `hypothesis_evidence` | #8 Hypothesis Generation | Yes |
| `hypothesis_generation_queue` | #8 Hypothesis Generation | Yes |
| `expectation_violation` | #9 Expectation Violation | Yes |
| `causal_candidate` | #10 Causal Direction | Yes |
| `causal_evidence_pair` | #10 Causal Direction | Yes |
| `causal_analysis_run` | #10 Causal Direction | Yes |

### Layer 4: Evidence

| Table | Owner Mechanism | New in v3 |
|---|---|---|
| `compression_discovery_event` | #11 Pattern Compression | Yes |
| `counterfactual_simulation_result` | #12 Counterfactual Sim | Yes |
| `counterfactual_pair_delta` | #12 Counterfactual Sim | Yes |
| `counterfactual_candidate_queue` | #12 Counterfactual Sim | Yes |
| `counterfactual_job_run` | #12 Counterfactual Sim | Yes |

### Layer 5: Insight

| Table | Owner Mechanism | New in v3 |
|---|---|---|
| `meta_memory_area` | #13 Meta-Memory | Yes |
| `meta_memory_productivity` | #13 Meta-Memory | Yes |
| `meta_memory_bias` | #13 Meta-Memory | Yes |
| `meta_memory_topological_region` | #13 Meta-Memory | Yes |
| `meta_memory_tenant_state` | #13 Meta-Memory | Yes |
| `meta_memory_job_run` | #13 Meta-Memory | Yes |
| `pattern_individual` | #14 Evolutionary Patterns | Yes |
| `pattern_individual_archive` | #14 Evolutionary Patterns | Yes |
| `evolution_generation_log` | #14 Evolutionary Patterns | Yes |
| `evolution_partition_state` | #14 Evolutionary Patterns | Yes |

**Total**: 12 Layer 1 tables (6 modified, 6 unchanged) + 22 Layer 2 tables (all new) + 7 Layer 3 tables (all new) + 5 Layer 4 tables (all new) + 10 Layer 5 tables (all new) = **56 tables**.

---

## 7. Startup and Initialization Order

Layers must initialize bottom-up. Within Layer 2, Tier 1 mechanisms must be ready before Tier 2 mechanisms start processing.

```
Phase 1: Layer 1 -- Correlation
  1a. Database schema migration (Alembic: all tables exist)
  1b. T-VEC model loading (lazy, background pre-warm)
  1c. TSLAM model loading (lazy, background pre-warm)
  1d. Enrichment chain ready
  1e. Snap engine ready (reads weight_profile_active -- uses defaults if empty)

Phase 2: Layer 2 -- Discovery (Tier 1)
  2a. Surprise distribution states loaded from surprise_distribution_state
  2b. Ignorance mapping job scheduled
  2c. Negative evidence service registered
  2d. Bridge detection hooks registered on accumulation graph changes

Phase 3: Layer 2 -- Discovery (Tier 2)
  3a. Outcome calibration reads snap_outcome_feedback + calibration_history
  3b. Conflict detector registered on snap_decision_record writes
  3c. Temporal sequence service ready (entity_sequence_log, transition_matrix)

Phase 4: Layer 3 -- Hypothesis
  4a. Violation detector registered on entity_sequence_log writes
  4b. Hypothesis generation queue consumer started
  4c. Causal direction analysis job scheduled

Phase 5: Layer 4 -- Evidence (batch only)
  5a. Pattern compression job scheduled
  5b. Counterfactual simulation job scheduled (maintenance window only)

Phase 6: Layer 5 -- Insight (batch only)
  6a. Meta-memory job scheduled
  6b. Evolutionary patterns generation cycle scheduled
```

---

## 8. Invariants

| ID | Statement | Enforcement Layer |
|---|---|---|
| INV-1 | Fragment lifecycle via SnapStatus enum (deterministic state machine) | L1 |
| INV-3 | All scores in [0.0, 1.0] | L1 |
| INV-5 | SNAPPED status is terminal for automated processes | L1 |
| INV-6 | raw_content bounded to 64KB; max_lifetime_days hard cap | L1 |
| INV-7 | tenant_id on every table, every query | All layers |
| INV-9 | MAX_EDGES_PER_FRAGMENT bounded | L1 |
| INV-10 | fragment_history, snap_decision_record are append-only | L1 |
| INV-11 | Mask vector consulted during scoring | L1, L2 (Ignorance), L4 (Compression) |
| INV-12 | NULL embedding = unknown; zero-fill prohibited | L1 |
| INV-13 | CHECK constraints enforce mask/embedding coherence at DB level | L1 |
| INV-14 | snap_decision_record stores five explicit per-dimension scores | L1 |
| INV-ARCH-1 | Mechanisms write only to their own layer's tables | All layers |
| INV-ARCH-2 | Mechanisms read only from own layer or lower layers | All layers |
| INV-ARCH-3 | Feedback loops are mediated through registry tables, never direct mutation | L2->L1 (weights), L5->L1 (bias) |
| INV-ARCH-4 | Within Layer 2, Tier 2 may read Tier 1 outputs; Tier 1 must not read Tier 2 | L2 |
| INV-ARCH-5 | Layer 4 and Layer 5 mechanisms are batch-only; no real-time side effects | L4, L5 |

---

## 9. Naming Convention Summary

All table names follow snake_case. Mechanism-specific tables are prefixed by their mechanism's domain concept:

| Prefix | Mechanism | Tables |
|---|---|---|
| `surprise_` | #1 Surprise Metrics | 2 tables |
| `ignorance_` | #2 Ignorance Mapping | 7 tables |
| `disconfirmation_` | #3 Negative Evidence | 3 tables |
| `bridge_discovery` | #4 Bridge Detection | 2 tables |
| `snap_outcome_` | #5 Outcome Calibration | 1 table |
| `calibration_` | #5 Outcome Calibration | 1 table |
| `weight_profile_` | #5 Outcome Calibration | 1 table |
| `conflict_` | #6 Pattern Conflict | 2 tables |
| `entity_sequence_` | #7 Temporal Sequence | 1 table |
| `transition_matrix` | #7 Temporal Sequence | 2 tables |
| `hypothesis` | #8 Hypothesis Generation | 3 tables |
| `expectation_violation` | #9 Expectation Violation | 1 table |
| `causal_` | #10 Causal Direction | 3 tables |
| `compression_` | #11 Pattern Compression | 1 table |
| `counterfactual_` | #12 Counterfactual Sim | 4 tables |
| `meta_memory_` | #13 Meta-Memory | 6 tables |
| `pattern_individual` / `evolution_` | #14 Evolutionary Patterns | 4 tables |

**Canonical table name for snap decisions**: `snap_decision_record` (NOT `snap_decision_log`). See Conflict 5.1.

---

Generated: 2026-03-16 | Phase 6 | Abeyance Memory v3.0 Cognitive Architecture
