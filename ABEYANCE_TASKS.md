# Abeyance Memory v3.0 Reconstruction — Atomic Task Backlog

Generated from: ABEYANCE_MEMORY_FORENSIC_AUDIT_V2.md + architecture decisions (2026-03-16)
Designed for: ABEYANCE-ORCHESTRATOR multi-agent execution
Total tasks: 38
Phases: 0-7

---

## Phase 0 — Research & Extraction

All Phase 0 tasks are read-only. No code modifications. Run fully in parallel.
Model tier: haiku for all.

---

### T0.1 — Extract Audit Findings Index

**Phase:** 0
**Model Tier:** haiku
**Context:** The forensic audit contains findings across sections 2-9. This task creates a structured index that all later agents consume instead of re-reading the full audit.
**Scope Boundary:**
  - DO: Read audit, extract and categorise every finding
  - DO NOT: Suggest fixes, design anything, read code
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/docs/ABEYANCE_MEMORY_FORENSIC_AUDIT_V2.md
**Deliverables:**
  - abeyance_orchestrator_run/research/audit_findings_index.md
**Acceptance Criteria:**
  - Every finding in audit sections 2-9 is listed
  - Each finding has: ID, severity, one-line summary, affected subsystem, root cause
  - Each finding is classified as: code bug | architectural flaw | missing feature | economic issue
  - No design recommendations included
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

### T0.2 — Extract LLD Invariants and Constraints

**Phase:** 0
**Model Tier:** haiku
**Context:** The LLD v2.0 defines invariants, safety guarantees, and architectural constraints that the reconstruction must preserve. This task extracts them as a structured reference.
**Scope Boundary:**
  - DO: Read LLD, extract every invariant, constraint, and safety guarantee
  - DO NOT: Suggest new invariants, design anything, read code
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/docs/ABEYANCE_MEMORY_LLD.md
**Deliverables:**
  - abeyance_orchestrator_run/research/lld_invariants.md
**Acceptance Criteria:**
  - Every invariant/constraint from LLD sections 3-5 is listed
  - Each has: ID/name, exact statement, enforcing subsystem
  - Cross-reference to audit findings where the audit found violations
  - No design recommendations included
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

### T0.3 — Extract Valid Strengths

**Phase:** 0
**Model Tier:** haiku
**Context:** The audit identifies components above 70% capability. These are load-bearing walls the reconstruction must not break.
**Scope Boundary:**
  - DO: Read audit, list every component rated above 70% with reasons
  - DO NOT: Assess components yourself, design anything
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/docs/ABEYANCE_MEMORY_FORENSIC_AUDIT_V2.md
**Deliverables:**
  - abeyance_orchestrator_run/research/valid_strengths.md
**Acceptance Criteria:**
  - Every component the audit rates above 70% is listed
  - Each has: component name, audit rating, specific reasons for the rating
  - Clearly marked as "do not break" constraints for later phases
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

### T0.4 — Extract Codebase Structure: Core Subsystems

**Phase:** 0
**Model Tier:** haiku
**Context:** Later agents need to know the current code structure without reading every file themselves.
**Scope Boundary:**
  - DO: Search codebase, extract structural facts for enrichment_chain, snap_engine, accumulation_graph, shadow_topology, cold_storage
  - DO NOT: Extract for other files, suggest fixes, design anything
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/backend/app/ (search, do not read in full)
**Deliverables:**
  - abeyance_orchestrator_run/research/codebase_core.md
**Acceptance Criteria:**
  - For each file: full path, public methods with signatures, constants/thresholds, DB tables touched, dependencies on other abeyance files, TODO/FIXME comments
  - Dependency graph showing which subsystem calls which
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

### T0.5 — Extract Codebase Structure: Support Subsystems

**Phase:** 0
**Model Tier:** haiku
**Context:** Same as T0.4 but for support subsystems.
**Scope Boundary:**
  - DO: Search codebase, extract structural facts for decay_engine, maintenance, telemetry_aligner, incident_reconstruction, value_attribution, abeyance_decay (deprecated)
  - DO NOT: Extract for core subsystems (T0.4 handles those)
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/backend/app/ (search, do not read in full)
**Deliverables:**
  - abeyance_orchestrator_run/research/codebase_support.md
**Acceptance Criteria:**
  - Same structure as T0.4 for each file
  - Deprecated module (abeyance_decay.py) flagged with import analysis
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

### T0.6 — Extract ORM Schema, API Endpoints, and Migrations

**Phase:** 0
**Model Tier:** haiku
**Context:** The embedding redesign requires knowing the exact current schema. The integration phase requires knowing all API endpoints.
**Scope Boundary:**
  - DO: Extract complete ORM schema, all API router endpoints, all Alembic migrations related to abeyance
  - DO NOT: Suggest schema changes
**Inputs:**
  - /Users/himanshu/Projects/Pedkai/backend/app/ (search for ORM models, routers, alembic)
**Deliverables:**
  - abeyance_orchestrator_run/research/orm_schema.md
  - abeyance_orchestrator_run/research/api_endpoints.md
**Acceptance Criteria:**
  - Every table, column, type, index, constraint in the abeyance ORM
  - Every API endpoint: path, method, handler function, file location
  - Every Alembic migration: revision ID, description, tables affected
**Dependencies:** None
**Parallelisation:** Fully parallel with all Phase 0 tasks

---

## Phase 1 — Embedding Architecture Redesign

Phase 1 runs in parallel with Phase 2. No dependencies between them.
All Phase 1 tasks depend on Phase 0 completion.

---

### T1.1 — T-VEC / TSLAM Serving Architecture

**Phase:** 1
**Model Tier:** opus
**Context:** T-VEC (1.5B, CPU) and TSLAM-8B (GPU) must be served within a FastAPI async runtime where loop.is_running() == True. This task designs the serving layer that all other embedding-dependent tasks build on.
**Scope Boundary:**
  - DO: Design model loading, serving, batching, resource isolation, async integration
  - DO NOT: Design the enrichment chain, snap engine, or schema (other tasks handle those)
**Inputs:**
  - Phase 0 research outputs (codebase structure)
  - Embedding architecture section from orchestrator prompt (injected by orchestrator)
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/serving_architecture.md
**Acceptance Criteria:**
  - T-VEC serving: model loading, run_in_executor wrapping, batch strategy, throughput estimate on CPU
  - TSLAM-8B serving: vLLM/TGI integration OR run_in_executor, GPU vs CPU paths
  - TSLAM-4B fallback: when and how to switch
  - Connection pooling / request queuing under load
  - Resource isolation: T-VEC (CPU) and TSLAM (GPU) do not contend
  - Async-compatible: no blocking calls in the event loop
  - Health check / readiness probe for each model
  - Failure modes: model OOM, model loading failure, inference timeout
**Dependencies:** T0.1, T0.2, T0.3, T0.4, T0.5, T0.6
**Parallelisation:** Parallel with T1.2, T1.3, T1.4, T1.5, T1.6

---

### T1.2 — Fragment ORM Schema Redesign

**Phase:** 1
**Model Tier:** opus
**Context:** Replace the single enriched_embedding Vector(1536) with four separate columns. This is the foundational schema change.
**Scope Boundary:**
  - DO: Design the new ORM table definitions for ActiveFragmentORM and ColdFragmentORM
  - DO NOT: Design enrichment chain logic, snap scoring logic, or serving architecture
**Inputs:**
  - abeyance_orchestrator_run/research/orm_schema.md (from T0.6)
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/orm_schema.md
**Acceptance Criteria:**
  - Complete ActiveFragmentORM: all existing columns preserved + four new embedding columns + three mask booleans
  - Complete ColdFragmentORM: same four-column schema
  - Drop: enriched_embedding, embedding_mask JSONB
  - Indexes: IVFFlat per T-VEC column on ColdFragmentORM, list count formula (sqrt(n))
  - All columns typed, constrained, and documented
  - Tenant isolation preserved
  - snap_decision_record updated: must store per-dimension scores (5 scores: semantic, topological, temporal, operational, entity_overlap)
**Dependencies:** T0.6
**Parallelisation:** Parallel with T1.1, T1.3, T1.4, T1.5, T1.6

---

### T1.3 — Enrichment Chain Redesign

**Phase:** 1
**Model Tier:** opus
**Context:** The enrichment chain produces the four embedding dimensions per fragment. Currently makes 4 LLM calls to a cloud API. Redesigned to use T-VEC (3 calls) + sinusoidal math (1 dimension).
**Scope Boundary:**
  - DO: Design per-fragment enrichment flow, input text construction per dimension, failure handling
  - DO NOT: Design the serving layer (T1.1), the schema (T1.2), or snap scoring (T1.4)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (enrichment chain section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 3.1, 3.2, 3.3)
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/enrichment_chain.md
**Acceptance Criteria:**
  - Step-by-step enrichment flow for each fragment:
    1. TSLAM-8B: entity extraction from fragment content -> entity list
    2. T-VEC: embed content + entities -> emb_semantic (1536)
    3. T-VEC: embed Shadow Topology neighbourhood description -> emb_topological (1536)
    4. Sinusoidal: time-of-day/day-of-week encoding -> emb_temporal (256)
    5. T-VEC: embed failure mode + operational fingerprint -> emb_operational (1536)
  - Input text construction specified for each T-VEC call (what text is fed to the model)
  - Shadow Topology fix: entity_identifiers passed to get_neighbourhood(), NOT empty list (audit finding 3.2)
  - Per-dimension failure handling: if T-VEC fails for one dimension, others still proceed, failed dimension gets NULL + mask FALSE
  - No hash embedding fallback anywhere (audit finding 3.3)
  - Async-compatible (assumes serving layer from T1.1 exists)
**Dependencies:** T0.4, T0.1
**Parallelisation:** Parallel with T1.1, T1.2, T1.4, T1.5, T1.6

---

### T1.4 — Snap Engine Scoring Redesign

**Phase:** 1
**Model Tier:** opus
**Context:** Scoring must operate per-dimension with mask-aware weight redistribution. Replaces single cosine over concatenated vector.
**Scope Boundary:**
  - DO: Design per-dimension scoring, weight redistribution, snap decision record structure
  - DO NOT: Design enrichment, schema, or discovery mechanisms
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (snap engine section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 2.4, 6.2)
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
**Acceptance Criteria:**
  - Per-dimension similarity: cosine(emb_semantic_a, emb_semantic_b), cosine(emb_topological_a, emb_topological_b), cosine(emb_temporal_a, emb_temporal_b), cosine(emb_operational_a, emb_operational_b)
  - Entity overlap: Jaccard(entities_a, entities_b) -- always available
  - Mask enforcement: only compute cosine where BOTH fragments have mask=TRUE for that dimension
  - Weight redistribution formula: when dimension unavailable, its weight distributed proportionally to available dimensions (exact formula specified)
  - Weight profile structure: 5 weights (semantic, topological, temporal, operational, entity_overlap) that sum to 1.0
  - Current weights documented as "initial estimates pending empirical validation" with methodology for validation (connects to Tier 2 Outcome-Linked Calibration)
  - snap_decision_record: stores all 5 per-dimension scores + which dimensions were available + final weighted score
  - Bounded arithmetic: no floating-point instability (LLD invariant)
  - Deterministic: same inputs always produce same score
**Dependencies:** T0.4, T0.1
**Parallelisation:** Parallel with T1.1, T1.2, T1.3, T1.5, T1.6

---

### T1.5 — Cold Storage Redesign

**Phase:** 1
**Model Tier:** sonnet
**Context:** Cold storage needs the same four-column schema and updated indexes.
**Scope Boundary:**
  - DO: Design cold storage schema, indexes, search strategy, expiration policy
  - DO NOT: Design active fragment schema (T1.2), enrichment (T1.3), or scoring (T1.4)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (cold_storage section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 3.4, 5.4, 8.2, 9.1)
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/cold_storage.md
**Acceptance Criteria:**
  - ColdFragmentORM with four embedding columns + masks
  - IVFFlat index per T-VEC column, list count = ceil(sqrt(n))
  - Search strategy: default query on emb_semantic, optional multi-index fusion
  - Expiration policy (audit finding 8.2)
  - Tenant_id sanitisation in Parquet path construction (audit finding 9.1)
  - Silent exception removal (audit finding 3.4) -- add logging + counters
**Dependencies:** T0.4, T0.1
**Parallelisation:** Parallel with T1.1, T1.2, T1.3, T1.4, T1.6

---

### T1.6 — Migration Strategy

**Phase:** 1
**Model Tier:** sonnet
**Context:** Existing fragments have concatenated embeddings that cannot be decomposed. Need a migration path.
**Scope Boundary:**
  - DO: Design Alembic migration steps, backfill approach, cutover criteria
  - DO NOT: Design the target schema (T1.2 handles that)
**Inputs:**
  - abeyance_orchestrator_run/research/orm_schema.md (current schema from T0.6)
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_1/migration_strategy.md
**Acceptance Criteria:**
  - Alembic migration: add new columns, add indexes, migrate mask data
  - Backfill: existing fragments get mask_*=FALSE on new columns (cannot decompose L2-normalised concatenated vectors)
  - Dual-write period: new fragments use new schema; old fragments decay naturally
  - Cutover: drop old columns when no old-schema fragments remain active
  - Rollback plan if migration fails
  - Zero-downtime migration (online, not offline)
**Dependencies:** T0.6
**Parallelisation:** Parallel with T1.1, T1.2, T1.3, T1.4, T1.5

---

## Phase 2 — Existing Subsystem Remediation

Phase 2 runs in parallel with Phase 1. No dependencies between them.
All Phase 2 tasks depend on Phase 0 completion.
All Phase 2 tasks are parallel within the phase.

---

### T2.1 — Accumulation Graph Remediation

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit findings 5.2 and 5.3: unbounded graph loads and N+1 edge pruning.
**Scope Boundary:**
  - DO: Specify exact fixes for accumulation graph query patterns
  - DO NOT: Design new discovery mechanisms that use the graph (Phase 3+ handles those)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (accumulation_graph section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 5.2, 5.3)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/accumulation_graph_fix.md
**Acceptance Criteria:**
  - Full-tenant edge loading replaced with paginated/streaming approach (exact SQL)
  - N+1 edge pruning replaced with single JOIN query (exact SQL)
  - Bounded: maximum edges loaded per query specified
  - Performance: complexity analysis before and after
**Dependencies:** T0.4, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.2 — Shadow Topology Wiring

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit finding 3.1: Shadow Topology exists but is unused. The enrichment chain redesign (Phase 1) will consume topology via emb_topological, but the Shadow Topology service interface itself may need changes.
**Scope Boundary:**
  - DO: Specify Shadow Topology service interface changes needed for the enrichment chain to consume it
  - DO NOT: Design the enrichment chain itself (T1.3 handles that)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (shadow_topology section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 3.1)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/shadow_topology_wiring.md
**Acceptance Criteria:**
  - get_neighbourhood() interface: accepts entity_identifiers list, returns structured neighbourhood description
  - topological_proximity() integration path specified
  - BFS depth limits documented
  - Performance: bounded query complexity
**Dependencies:** T0.4, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.3 — Maintenance Subsystem Remediation

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit findings 5.3, 7.3: N+1 query in prune_stale_edges(), no maintenance job history.
**Scope Boundary:**
  - DO: Fix maintenance queries, design job history table
  - DO NOT: Design observability metrics (T2.6 handles those)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_support.md (maintenance section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 5.3, 7.3)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/maintenance_fix.md
**Acceptance Criteria:**
  - N+1 query in prune_stale_edges() replaced with batch query (exact SQL)
  - Maintenance job history table: schema, columns, what is recorded per run
  - Job history persistence (not just in-memory)
**Dependencies:** T0.5, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.4 — Telemetry Aligner: Remove Hash Fallback

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit finding 3.3: hash embedding fallback produces incomparable vectors. Must be eliminated entirely.
**Scope Boundary:**
  - DO: Specify removal of hash embedding path, specify T-VEC integration point
  - DO NOT: Design T-VEC serving (T1.1), enrichment chain (T1.3)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_support.md (telemetry_aligner section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 3.3)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/telemetry_aligner_fix.md
**Acceptance Criteria:**
  - Hash embedding code path removed entirely
  - Integration point for T-VEC specified (calls serving layer from T1.1)
  - Failure path: if T-VEC unavailable, embedding is NULL + mask FALSE
  - No zero-filled vectors anywhere
**Dependencies:** T0.5, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.5 — Decay Engine: Accelerated Decay Interface

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit finding 4.4: decay is time-based only. Negative evidence (Phase 3) needs to accelerate decay. This task adds the interface; Phase 3 T3.3 designs the logic.
**Scope Boundary:**
  - DO: Add external decay acceleration interface to decay engine
  - DO NOT: Design the negative evidence mechanism (Phase 3 T3.3 handles that)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_support.md (decay_engine section)
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 4.4)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/decay_engine_interface.md
**Acceptance Criteria:**
  - New method: apply_accelerated_decay(fragment_id, acceleration_factor, reason, provenance)
  - acceleration_factor bounded (e.g., 2x-10x normal rate, not arbitrary)
  - Provenance logged: who triggered, why, what factor
  - Monotonic decay invariant preserved (acceleration speeds up but does not reverse)
  - LLD safety guarantees maintained
**Dependencies:** T0.5, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.6 — Observability Metrics Design

**Phase:** 2
**Model Tier:** sonnet
**Context:** Audit findings 7.1, 7.2, 7.3: no operational observability.
**Scope Boundary:**
  - DO: Design all metrics, counters, histograms, and alerting
  - DO NOT: Design discovery mechanisms or implement metrics (specification only)
**Inputs:**
  - abeyance_orchestrator_run/research/audit_findings_index.md (findings 7.1, 7.2, 7.3)
  - abeyance_orchestrator_run/research/codebase_core.md
  - abeyance_orchestrator_run/research/codebase_support.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/observability.md
**Acceptance Criteria:**
  - Fragment counters: ingested/decayed/snapped per unit time per tenant
  - Snap score histograms per failure mode profile
  - Active fragment gauge per tenant
  - Enrichment chain latency: per-dimension (T-VEC semantic, T-VEC topo, sinusoidal, T-VEC operational, TSLAM entity extraction)
  - T-VEC / TSLAM error rates and latency percentiles
  - Maintenance job history metrics
  - Embedding mask distribution (% fragments with each dimension valid)
  - All metrics: Prometheus-compatible naming, types (counter/gauge/histogram), labels
  - Emission points: where in code each metric is emitted
**Dependencies:** T0.4, T0.5, T0.1
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.7 — Failure Recovery Procedures

**Phase:** 2
**Model Tier:** sonnet
**Context:** The system needs deterministic recovery for multiple failure scenarios, especially with the new local-LLM architecture.
**Scope Boundary:**
  - DO: Design recovery procedures for all failure scenarios
  - DO NOT: Design the systems that fail (other tasks handle those)
**Inputs:**
  - abeyance_orchestrator_run/research/lld_invariants.md
  - abeyance_orchestrator_run/research/codebase_core.md
  - Embedding architecture section from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/failure_recovery.md
**Acceptance Criteria:**
  - T-VEC unavailability: NULL embeddings, FALSE masks, backfill on recovery
  - TSLAM-8B unavailability: regex fallback for entity extraction, hypothesis generation queued
  - Redis loss: what state is lost, what is recoverable from PostgreSQL WAL
  - Vector index corruption: IVFFlat rebuild procedure per column, impact during rebuild
  - Partial event loss: mask-based detection, re-enrichment of missing dimensions
  - Mid-enrichment crash: detection (all masks FALSE + stale created_at), recovery or expiry
  - Clustering instability: dampening strategy for edge churn
  - Each scenario: detection method, recovery steps, data loss assessment, SLA impact
**Dependencies:** T0.2, T0.4
**Parallelisation:** Parallel with all Phase 2 tasks

---

### T2.8 — Deprecated Module Removal

**Phase:** 2
**Model Tier:** haiku
**Context:** Audit finding 3.5: abeyance_decay.py is deprecated but still present.
**Scope Boundary:**
  - DO: Identify all imports/references, specify removal
  - DO NOT: Modify the active decay engine
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_support.md (abeyance_decay section)
**Deliverables:**
  - abeyance_orchestrator_run/phase_2/deprecated_removal.md
**Acceptance Criteria:**
  - abeyance_decay.py removal confirmed safe (no active imports)
  - Associated test file removal
  - List of all files checked for references
**Dependencies:** T0.5
**Parallelisation:** Parallel with all Phase 2 tasks

---

## Phase 3 — Tier 1 Discovery Mechanisms

Waits for Phase 0, Phase 1, and Phase 2 to complete.
All Phase 3 tasks are parallel within the phase (Tier 1 mechanisms have no mutual dependencies).

---

### T3.1 — Surprise Metrics Engine

**Phase:** 3
**Model Tier:** opus
**Context:** Discovery mechanism #1. Score: -log(P(observation | current model)). Track rolling distributions of snap scores, flag statistical outliers. Also serves as anomalous snap rate detection (audit finding 7.2).
**Scope Boundary:**
  - DO: Design the surprise engine algorithm, storage, and interfaces
  - DO NOT: Design other discovery mechanisms or modify the snap engine
**Inputs:**
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 7.2)
  - abeyance_orchestrator_run/phase_1/snap_scoring.md (snap decision record structure)
  - Discovery tier structure from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_3/surprise_engine.md
**Acceptance Criteria:**
  - Algorithm: rolling distribution per failure mode profile per tenant
  - Distribution estimator specified (e.g., kernel density, histogram bins)
  - Rolling window size and update frequency defined
  - Surprise threshold derivation methodology (not arbitrary)
  - -log(P) computation with bounded arithmetic
  - Trigger: high surprise -> escalation to discovery evaluation
  - Storage: new table schema with tenant isolation
  - Provenance: what is logged when surprise is triggered
  - Concrete telecom example (e.g., unusual snap score for eNB alarm pattern)
  - Computational complexity: O(?) per snap evaluation
  - Failure mode: what happens with insufficient data for distribution estimation
**Dependencies:** T0.1, T1.4
**Parallelisation:** Parallel with T3.2, T3.3, T3.4

---

### T3.2 — Ignorance Mapping

**Phase:** 3
**Model Tier:** sonnet
**Context:** Discovery mechanism #2. Surface sparse, unstable, or low-confidence regions of the evidence space. Read what the system already writes (mask distributions, entity extraction rates) and identify blind spots.
**Scope Boundary:**
  - DO: Design ignorance mapping algorithm, storage, and interfaces
  - DO NOT: Design other mechanisms or modify existing subsystems
**Inputs:**
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 4.2)
  - abeyance_orchestrator_run/phase_1/orm_schema.md (mask columns)
  - abeyance_orchestrator_run/phase_2/observability.md (metric definitions)
**Deliverables:**
  - abeyance_orchestrator_run/phase_3/ignorance_mapping.md
**Acceptance Criteria:**
  - Tracks: entity extraction success rates per entity type, source type, time window
  - Tracks: mask distribution (% fragments with each dimension valid)
  - Identifies: fragments that decay to zero without evaluation (audit finding 4.2)
  - Quantitative definition of "high ignorance" region
  - Exploration directive: how ignorance maps direct future enrichment priority
  - Storage schema with tenant isolation
  - Provenance logging
  - Concrete telecom example
  - Computational complexity bounded
**Dependencies:** T0.1, T1.2, T2.6
**Parallelisation:** Parallel with T3.1, T3.3, T3.4

---

### T3.3 — Negative Evidence / Disconfirmation Engine

**Phase:** 3
**Model Tier:** opus
**Context:** Discovery mechanism #3. Addresses audit finding 4.4. The system currently cannot anti-corroborate. Decay is time-based only. Adds operator-driven and system-driven disconfirmation.
**Scope Boundary:**
  - DO: Design negative evidence mechanism, propagation, and accelerated decay trigger
  - DO NOT: Modify the decay engine interface (T2.5 already added it)
**Inputs:**
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 4.4)
  - abeyance_orchestrator_run/phase_2/decay_engine_interface.md (accelerated decay API)
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_3/negative_evidence.md
**Acceptance Criteria:**
  - Operator-driven: API for reclassifying ACTIVE fragments as "investigated, not relevant"
  - Accelerated decay: calls apply_accelerated_decay() from T2.5
  - Propagation: disconfirmed patterns reduce snap scores for similar future fragments
  - Propagation radius defined and bounded
  - Decay acceleration formula defined and bounded
  - API endpoint specification
  - Storage: disconfirmation record schema with provenance
  - Does NOT break monotonic decay invariant
  - Concrete telecom example (e.g., operator dismisses false alarm pattern, similar future fragments decay faster)
**Dependencies:** T0.1, T2.5, T1.4
**Parallelisation:** Parallel with T3.1, T3.2, T3.4

---

### T3.4 — Cross-Cluster Bridge Detection

**Phase:** 3
**Model Tier:** sonnet
**Context:** Discovery mechanism #4. Detect articulation points and high-betweenness fragments in the accumulation graph. Pure graph algorithm, no LLM.
**Scope Boundary:**
  - DO: Design bridge detection algorithm on the accumulation graph
  - DO NOT: Modify the accumulation graph itself (T2.1 handles remediation)
**Inputs:**
  - abeyance_orchestrator_run/research/codebase_core.md (accumulation_graph section)
  - abeyance_orchestrator_run/phase_2/accumulation_graph_fix.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_3/bridge_detection.md
**Acceptance Criteria:**
  - Algorithm: articulation point detection + betweenness centrality (or approximation)
  - Definition: when a bridge fragment constitutes a "discovery" vs routine connectivity
  - Bounded computation: does not require full graph load (respects T2.1 pagination)
  - Storage: bridge discovery record schema
  - Provenance: which clusters were connected, through which fragment
  - Concrete telecom example (e.g., fragment connecting power-grid alarms to RAN alarms)
  - Computational complexity bounded
**Dependencies:** T0.4, T2.1
**Parallelisation:** Parallel with T3.1, T3.2, T3.3

---

## Phase 4 — Tier 2 Discovery Mechanisms

Waits for Phase 3 to complete.
All Phase 4 tasks are parallel within the phase.

---

### T4.1 — Outcome-Linked Scoring Calibration

**Phase:** 4
**Model Tier:** opus
**Context:** Discovery mechanism #5. Connect operator resolution actions back to snap scores. Prerequisite for resolving audit finding 2.4 (arbitrary weights) with data.
**Scope Boundary:**
  - DO: Design outcome tracking, feedback table, calibration algorithm
  - DO NOT: Modify the snap engine scoring (T1.4) -- define the interface this mechanism uses to feed calibrated weights back
**Inputs:**
  - abeyance_orchestrator_run/phase_1/snap_scoring.md (weight profile, snap_decision_record)
  - abeyance_orchestrator_run/research/audit_findings_index.md (finding 2.4)
**Deliverables:**
  - abeyance_orchestrator_run/phase_4/outcome_calibration.md
**Acceptance Criteria:**
  - Feedback table: snap_decision_record_id -> operator_action (acknowledge/dismiss/escalate/resolve) -> outcome classification (true positive/false positive/missed)
  - Calibration algorithm: e.g., logistic regression on per-dimension scores predicting true-positive outcomes
  - Minimum sample size before calibration activates
  - Weight update frequency and bounds (weights can't swing wildly)
  - Feedback loop: calibrated weights fed back to snap engine weight profiles
  - Cold start: methodology documented for initial weights before calibration data exists
  - Storage schema with tenant isolation
  - Provenance: calibration history logged
  - Concrete telecom example
**Dependencies:** T1.4, T0.1
**Parallelisation:** Parallel with T4.2, T4.3

---

### T4.2 — Pattern Conflict Detection

**Phase:** 4
**Model Tier:** sonnet
**Context:** Discovery mechanism #6. Identify contradictions: high entity overlap + opposite polarity within time window. Surface conflicts for investigation without attempting automated resolution.
**Scope Boundary:**
  - DO: Design conflict detection algorithm and storage
  - DO NOT: Design hidden variable search or automated resolution
**Inputs:**
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
  - abeyance_orchestrator_run/phase_1/orm_schema.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_4/conflict_detection.md
**Acceptance Criteria:**
  - Definition: "opposite polarity" for telecom fragments (e.g., link_up vs link_down for same entity)
  - Time window for conflict relevance
  - Entity overlap threshold for conflict candidacy
  - Storage: conflict record schema (fragment pair, entity overlap, polarity description, time delta)
  - Provenance: conflict detection log
  - Explicit scope limit: "surfaces conflict, does not resolve"
  - Concrete telecom example
**Dependencies:** T1.4, T1.2
**Parallelisation:** Parallel with T4.1, T4.3

---

### T4.3 — Temporal Sequence Modelling

**Phase:** 4
**Model Tier:** opus
**Context:** Discovery mechanism #7. Per-entity ordered fragment logs and transition probability matrices. Cheap infrastructure that enables expectation violation detection in Tier 3.
**Scope Boundary:**
  - DO: Design sequence log storage, transition matrix computation, update rules
  - DO NOT: Design expectation violation detection (T5.2 handles that)
**Inputs:**
  - abeyance_orchestrator_run/phase_1/orm_schema.md (entity data in fragments)
  - abeyance_orchestrator_run/research/codebase_core.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_4/temporal_sequence.md
**Acceptance Criteria:**
  - Per-entity ordered log: entity_id -> [(timestamp, fragment_type/state, fragment_id), ...]
  - Transition probability matrix: P(state_j | state_i) per entity (or entity type)
  - Counting-based estimation (no LLM)
  - Sequence window: how far back to look
  - Minimum observation count for stable transition probability
  - Storage schema with tenant isolation
  - Update rule: how matrix updates as new fragments arrive
  - Provenance: matrix version history
  - Concrete telecom example (e.g., eNB state transitions: normal -> degraded -> alarm -> recovery)
**Dependencies:** T1.2, T0.4
**Parallelisation:** Parallel with T4.1, T4.2

---

## Phase 5 — Tier 3+4 Discovery Mechanisms

Waits for Phase 4 to complete.
All Phase 5 tasks are parallel within the phase.

---

### T5.1 — Hypothesis Generation Engine

**Phase:** 5
**Model Tier:** opus
**Context:** Discovery mechanism #8. TSLAM-8B converts recurring snap patterns into falsifiable claims. Replace hypothesis_id UUID label with a real hypothesis object.
**Scope Boundary:**
  - DO: Design hypothesis object, generation flow, lifecycle, storage
  - DO NOT: Design TSLAM serving (T1.1) or snap engine (T1.4)
**Inputs:**
  - abeyance_orchestrator_run/phase_1/serving_architecture.md (TSLAM-8B serving)
  - abeyance_orchestrator_run/phase_1/snap_scoring.md (snap_decision_record)
  - abeyance_orchestrator_run/phase_3/surprise_engine.md (surprise triggers)
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/hypothesis_engine.md
**Acceptance Criteria:**
  - Hypothesis object schema: claim_text, confirmation_conditions, refutation_conditions, confidence, supporting_evidence[], contradicting_evidence[], status (proposed/testing/confirmed/refuted/retired), created_at, updated_at, tenant_id
  - Generation trigger: recurring snap pattern or surprise-triggered escalation
  - TSLAM-8B prompt template: snap pair context -> falsifiable claim
  - Lifecycle: proposed -> testing -> confirmed/refuted -> retired
  - Evidence accumulation: how new snaps confirm or refute existing hypotheses
  - Async-compatible (TSLAM may be slow/unavailable)
  - Failure mode: if TSLAM unavailable, hypothesis generation queued for retry
  - Storage schema with tenant isolation
  - Provenance: full generation and evolution history
  - Concrete telecom example
**Dependencies:** T1.1, T1.4, T3.1
**Parallelisation:** Parallel with T5.2, T5.3, T5.4, T5.5, T5.6, T5.7

---

### T5.2 — Expectation Violation Detection

**Phase:** 5
**Model Tier:** opus
**Context:** Discovery mechanism #9. Compare observed entity state transitions against transition probability matrices from T4.3. Flag deviations.
**Scope Boundary:**
  - DO: Design violation detection algorithm, severity scoring, alerting
  - DO NOT: Design the sequence model (T4.3) or surprise engine (T3.1)
**Inputs:**
  - abeyance_orchestrator_run/phase_4/temporal_sequence.md (transition matrices)
  - abeyance_orchestrator_run/phase_3/surprise_engine.md (surprise scoring)
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/expectation_violation.md
**Acceptance Criteria:**
  - Algorithm: compare observed transition against P(state_j | state_i) from matrix
  - Violation severity = surprise of unexpected transition (-log(P))
  - Threshold: minimum matrix confidence before violations are meaningful
  - Expected vs observed comparison stored for explainability
  - Storage: violation record schema
  - Provenance: matrix version used, observed sequence, expected distribution
  - Concrete telecom example (e.g., expected: link_down -> recovery within 2h, observed: link_down -> cascading_failure)
**Dependencies:** T4.3, T3.1
**Parallelisation:** Parallel with T5.1, T5.3, T5.4, T5.5, T5.6, T5.7

---

### T5.3 — Causal Direction Testing

**Phase:** 5
**Model Tier:** sonnet
**Context:** Discovery mechanism #10. Granger-style temporal precedence. If fragments about entity A consistently precede fragments about entity B by stable lag, flag as directional causal candidate.
**Scope Boundary:**
  - DO: Design causal direction testing algorithm and storage
  - DO NOT: Design counterfactual simulation (T5.5) or sequence model (T4.3)
**Inputs:**
  - abeyance_orchestrator_run/phase_4/temporal_sequence.md (per-entity logs)
  - abeyance_orchestrator_run/phase_1/orm_schema.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/causal_direction.md
**Acceptance Criteria:**
  - Algorithm: lag estimation between entity pairs with consistent temporal ordering
  - Minimum sample size for confident lag estimation
  - Confidence metric for directional claim
  - Explicit caveat: temporal precedence != proof of causation
  - Storage: causal candidate record (entity_a, entity_b, mean_lag, sample_size, confidence)
  - Provenance: evidence fragment pairs
  - Concrete telecom example
**Dependencies:** T4.3, T1.2
**Parallelisation:** Parallel with T5.1, T5.2, T5.4, T5.5, T5.6, T5.7

---

### T5.4 — Pattern Compression Discovery

**Phase:** 5
**Model Tier:** sonnet
**Context:** Discovery mechanism #11. Collapse multiple snap patterns into simpler rules. Compression gain = discovery signal.
**Scope Boundary:**
  - DO: Define pattern grammar, compression algorithm, compression gain metric
  - DO NOT: Design other mechanisms
**Inputs:**
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
  - abeyance_orchestrator_run/phase_3/surprise_engine.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/pattern_compression.md
**Acceptance Criteria:**
  - Pattern grammar defined (what constitutes a "pattern" in this system)
  - Compression algorithm: how multiple patterns collapse into simpler rules
  - Compression gain: quantitative definition
  - When compression gain constitutes a discovery
  - Bounded computation
  - Concrete telecom example
**Dependencies:** T1.4, T3.1
**Parallelisation:** Parallel with all Phase 5 tasks

---

### T5.5 — Counterfactual Simulation

**Phase:** 5
**Model Tier:** sonnet
**Context:** Discovery mechanism #12. Remove candidate events from historical sequences and re-run snap scoring. Batch job only.
**Scope Boundary:**
  - DO: Design simulation framework, replay scope, batch scheduling
  - DO NOT: Design snap engine (T1.4) or sequence model (T4.3)
**Inputs:**
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
  - abeyance_orchestrator_run/phase_4/temporal_sequence.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/counterfactual_simulation.md
**Acceptance Criteria:**
  - "Remove and re-score" defined operationally
  - Replay scope bounded (max fragments, max time window)
  - Batch job scheduling: maintenance window only, not real-time
  - Causal impact metric: difference in downstream snap scores
  - Storage: simulation result records
  - Computational complexity: O(n) replays per candidate, total bounded
  - Concrete telecom example
**Dependencies:** T1.4, T4.3
**Parallelisation:** Parallel with all Phase 5 tasks

---

### T5.6 — Meta-Memory

**Phase:** 5
**Model Tier:** sonnet
**Context:** Discovery mechanism #13. Track historically productive vs fruitless search areas. Requires outcome data from T4.1.
**Scope Boundary:**
  - DO: Design productivity tracking, bias algorithm, storage
  - DO NOT: Design outcome tracking (T4.1) or other mechanisms
**Inputs:**
  - abeyance_orchestrator_run/phase_4/outcome_calibration.md (outcome data)
  - abeyance_orchestrator_run/phase_3/ignorance_mapping.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/meta_memory.md
**Acceptance Criteria:**
  - Productivity metric defined: what makes a search area "productive" (requires outcome data)
  - Tracked dimensions: entity types, failure modes, time windows, topological regions
  - Bias algorithm: how exploration effort shifts toward productive areas
  - Bias bounds: cannot completely abandon any area (exploration/exploitation balance)
  - Failure mode: insufficient outcome data -> meta-memory inactive (does not degenerate to volume tracking)
  - Storage schema
  - Concrete telecom example
**Dependencies:** T4.1, T3.2
**Parallelisation:** Parallel with all Phase 5 tasks

---

### T5.7 — Evolutionary Pattern Discovery

**Phase:** 5
**Model Tier:** sonnet
**Context:** Discovery mechanism #14. Treat confirmed patterns as evolving entities with fitness. Most complex mechanism; requires all preceding tiers.
**Scope Boundary:**
  - DO: Design fitness function, selection/mutation/recombination, storage
  - DO NOT: Design prerequisite mechanisms
**Inputs:**
  - abeyance_orchestrator_run/phase_4/outcome_calibration.md (predictive power)
  - abeyance_orchestrator_run/phase_3/surprise_engine.md (novelty)
  - abeyance_orchestrator_run/phase_5/pattern_compression.md (compression)
**Deliverables:**
  - abeyance_orchestrator_run/phase_5/evolutionary_patterns.md
**Acceptance Criteria:**
  - Fitness function: f(predictive_power, stability, novelty, compression)
  - Each fitness component sourced from a specific mechanism (cross-referenced)
  - Selection operator: which patterns survive
  - Mutation operator: how patterns vary
  - Recombination operator: how patterns merge
  - Population management: bounded population size
  - Generation schedule: when evolution runs (batch, not real-time)
  - Failure mode: insufficient data from prerequisites -> mechanism inactive
  - Storage schema
  - Concrete telecom example
**Dependencies:** T4.1, T3.1, T5.4
**Parallelisation:** Parallel with T5.1-T5.3, T5.5, T5.6 (but T5.4 must complete first for compression input)

---

## Phase 6 — Integration & Architecture

Waits for Phases 1-5 to complete.
Phase 6 tasks are mostly parallel.

---

### T6.1 — Cognitive Architecture Layers

**Phase:** 6
**Model Tier:** opus
**Context:** Define the five-layer architecture that organises all mechanisms.
**Scope Boundary:**
  - DO: Define layers, map mechanisms to layers, show data flow, resolve conflicts between prior agents
  - DO NOT: Redesign individual mechanisms
**Inputs:**
  - All Phase 1 deliverables
  - All Phase 3-5 deliverables
**Deliverables:**
  - abeyance_orchestrator_run/phase_6/cognitive_architecture.md
**Acceptance Criteria:**
  - Five layers: Correlation | Discovery | Hypothesis | Evidence | Insight
  - Each of 14 mechanisms mapped to exactly one layer
  - Data flow between layers specified
  - Tier dependencies shown
  - Conflicts between agents' outputs identified and RESOLVED (not just flagged)
  - Table naming consistency across all mechanisms verified
  - Tenant isolation pattern consistency verified
**Dependencies:** All Phase 1, 3, 4, 5 deliverables
**Parallelisation:** Parallel with T6.2, T6.3, T6.4, T6.5

---

### T6.2 — Discovery Loop Specification

**Phase:** 6
**Model Tier:** opus
**Context:** Define the exact deterministic flow from signal to discovery.
**Scope Boundary:**
  - DO: Define the end-to-end flow with entry/exit conditions at each stage
  - DO NOT: Redesign individual mechanisms
**Inputs:**
  - abeyance_orchestrator_run/phase_6/cognitive_architecture.md (if available, otherwise all Phase 3-5 deliverables)
  - abeyance_orchestrator_run/phase_1/enrichment_chain.md
  - abeyance_orchestrator_run/phase_1/snap_scoring.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_6/discovery_loop.md
**Acceptance Criteria:**
  - Flow: Signal -> Enrichment -> Correlation -> Surprise Evaluation -> Hypothesis -> Testing -> Confirmation/Refutation -> Discovery
  - Each stage: entry conditions, processing subsystems, output, exit conditions, provenance
  - Failure path at each stage
  - Deterministic: same inputs always produce same flow
  - Bounded: no infinite loops, maximum iterations per cycle
**Dependencies:** T1.3, T1.4, T3.1, T5.1
**Parallelisation:** Parallel with T6.1, T6.3, T6.4, T6.5

---

### T6.3 — Hard System Invariants (Final)

**Phase:** 6
**Model Tier:** opus
**Context:** Merge LLD v2.0 invariants with new invariants from the redesign.
**Scope Boundary:**
  - DO: Define all invariants for the v3.0 system
  - DO NOT: Redesign subsystems
**Inputs:**
  - abeyance_orchestrator_run/research/lld_invariants.md (v2.0 invariants)
  - All Phase 1-5 deliverables (new invariants implied by each design)
**Deliverables:**
  - abeyance_orchestrator_run/phase_6/invariants.md
**Acceptance Criteria:**
  - Every v2.0 invariant preserved or explicitly superseded with justification
  - New invariants for: embedding validity, mask enforcement, hypothesis lifecycle, discovery reproducibility, negative evidence propagation, outcome tracking integrity
  - Each invariant: ID, statement, testable assertion, enforcing subsystem, violation consequence
  - No gaps: every state transition in the system is covered by at least one invariant
**Dependencies:** T0.2, all Phase 1-5 deliverables
**Parallelisation:** Parallel with T6.1, T6.2, T6.4, T6.5

---

### T6.4 — Explainability Layer

**Phase:** 6
**Model Tier:** sonnet
**Context:** Define how every discovery is explained to operators.
**Scope Boundary:**
  - DO: Design the explainability interface and provenance assembly
  - DO NOT: Redesign individual mechanisms' provenance (already specified per-mechanism)
**Inputs:**
  - All Phase 3-5 deliverables (provenance specs per mechanism)
  - abeyance_orchestrator_run/phase_1/snap_scoring.md (per-dimension scores)
**Deliverables:**
  - abeyance_orchestrator_run/phase_6/explainability.md
**Acceptance Criteria:**
  - Every discovery includes: provenance DAG, per-dimension scoring breakdown, causal trace (if Tier 3+), hypothesis evolution, contradiction resolution log
  - Operator-facing format: answers "why did the system flag this?" with specific evidence
  - Per-dimension breakdown: not blended scores
  - API response structure for discovery explanations
**Dependencies:** All Phase 3-5 deliverables, T1.4
**Parallelisation:** Parallel with T6.1, T6.2, T6.3, T6.5

---

### T6.5 — Scalability Analysis

**Phase:** 6
**Model Tier:** sonnet
**Context:** Model performance at scale with the new architecture.
**Scope Boundary:**
  - DO: Analyse bottlenecks, estimate capacity limits, identify horizontal scaling triggers
  - DO NOT: Redesign subsystems for scale (specification only)
**Inputs:**
  - abeyance_orchestrator_run/phase_2/failure_recovery.md
  - abeyance_orchestrator_run/phase_1/serving_architecture.md
  - abeyance_orchestrator_run/phase_2/accumulation_graph_fix.md
  - abeyance_orchestrator_run/phase_1/cold_storage.md
**Deliverables:**
  - abeyance_orchestrator_run/phase_6/scalability.md
**Acceptance Criteria:**
  - Target: 50M active fragments, 10K-100K events/sec, 100 tenants
  - T-VEC throughput on CPU (batched, 1.5B model): estimated tokens/sec, fragments/sec
  - TSLAM-8B throughput: GPU vs CPU, estimated fragments/sec
  - pgvector IVFFlat at 50M rows per index: query latency estimates
  - Accumulation graph at scale: remediated query performance
  - Cold storage volume projections and expiration impact
  - Discovery mechanism batch jobs: scheduling constraints at scale
  - Concrete capacity limits and horizontal scaling triggers
**Dependencies:** T1.1, T1.5, T2.1, T2.7
**Parallelisation:** Parallel with T6.1, T6.2, T6.3, T6.4

---

## Phase 7 — Assembly & Validation

Waits for Phase 6 to complete. Sequential within phase.

---

### T7.1 — Assemble LLD v3.0

**Phase:** 7
**Model Tier:** sonnet
**Context:** Merge all deliverables into a single coherent LLD document that supersedes v2.0.
**Scope Boundary:**
  - DO: Assemble, format, resolve cross-references, ensure consistency
  - DO NOT: Redesign anything — assembly only
**Inputs:**
  - abeyance_orchestrator_run/research/valid_strengths.md (forensic ground truth)
  - All Phase 1 deliverables (embedding architecture)
  - All Phase 2 deliverables (remediation + ops)
  - All Phase 3-5 deliverables (discovery mechanisms)
  - All Phase 6 deliverables (integration)
**Deliverables:**
  - abeyance_orchestrator_run/phase_7/ABEYANCE_MEMORY_LLD_V3.md
**Acceptance Criteria:**
  - Complete, self-contained document
  - Sections: Forensic Ground Truth, Hard System Invariants, Cognitive Architecture, Embedding Architecture, Enrichment Chain, Snap Engine, all 14 Discovery Mechanisms (in tier order), Existing Subsystem Remediations, Discovery Loop, Explainability Layer, Observability, Failure Recovery, Scalability, Migration Strategy
  - Every audit finding cross-referenced with its resolution
  - Consistent formatting, numbering, and terminology throughout
  - No contradictions between sections
  - Version: 3.0, supersedes v2.0
**Dependencies:** All Phase 6 deliverables
**Parallelisation:** Must complete before T7.2

---

### T7.2 — Validate Acceptance Criteria

**Phase:** 7
**Model Tier:** sonnet
**Context:** Verify that the assembled LLD v3.0 meets all system-level acceptance criteria.
**Scope Boundary:**
  - DO: Validate completeness and correctness against acceptance criteria
  - DO NOT: Modify the LLD — produce a validation report only
**Inputs:**
  - abeyance_orchestrator_run/phase_7/ABEYANCE_MEMORY_LLD_V3.md
  - abeyance_orchestrator_run/research/audit_findings_index.md (all findings)
  - Acceptance criteria from orchestrator prompt
**Deliverables:**
  - abeyance_orchestrator_run/phase_7/validation_report.md
**Acceptance Criteria:**
  - Checklist: each acceptance criterion from orchestrator prompt -> PASS/FAIL with evidence
  - Audit coverage: each finding ID -> resolution location in LLD v3.0 or FAIL
  - Mechanism completeness: each of 14 mechanisms -> present with full spec or FAIL
  - Tier dependency check: no mechanism specified without prerequisite infrastructure
  - Embedding check: no hash fallback or zero-filling anywhere in spec
  - Provenance check: every discovery has reproducible provenance
  - Any FAILs trigger repair loop
**Dependencies:** T7.1
**Parallelisation:** Sequential after T7.1

---

## Dependency Summary

```
Phase 0: T0.1, T0.2, T0.3, T0.4, T0.5, T0.6         (all parallel)
          |
          v
Phase 1: T1.1, T1.2, T1.3, T1.4, T1.5, T1.6         (all parallel, concurrent with Phase 2)
Phase 2: T2.1, T2.2, T2.3, T2.4, T2.5, T2.6, T2.7, T2.8  (all parallel, concurrent with Phase 1)
          |
          v
Phase 3: T3.1, T3.2, T3.3, T3.4                       (all parallel)
          |
          v
Phase 4: T4.1, T4.2, T4.3                             (all parallel)
          |
          v
Phase 5: T5.1, T5.2, T5.3, T5.4, T5.5, T5.6, T5.7   (mostly parallel, T5.7 waits on T5.4)
          |
          v
Phase 6: T6.1, T6.2, T6.3, T6.4, T6.5                (all parallel)
          |
          v
Phase 7: T7.1 -> T7.2                                  (sequential)
```

Total tasks: 38
Critical path phases: 7 (but Phases 1+2 are concurrent)
Maximum parallel width: 8 (Phase 2)
Minimum sequential depth: 6 phase boundaries
