# Abeyance Memory v3.0 — Support Subsystems Codebase Structure

**Task:** Extract structural facts for decay_engine, maintenance, telemetry_aligner, incident_reconstruction, value_attribution, abeyance_decay (deprecated)

**Generated:** 2026-03-16

---

## 1. decay_engine.py

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/decay_engine.py`

### Public Methods with Signatures

#### `DecayEngine.__init__(provenance: ProvenanceLogger, notifier: Optional[RedisNotifier] = None)`
- Initializes decay engine with provenance logging and Redis notification.

#### `@staticmethod DecayEngine.compute_boost_factor(near_miss_count: int) -> float`
- Computes bounded boost factor from near-miss count.
- Returns value in `[1.0, MAX_BOOST_FACTOR]`.

#### `@staticmethod DecayEngine.compute_decay_score(base_relevance: float, near_miss_count: int, age_days: float, source_type: str) -> float`
- Pure computation of decay score (deterministic).
- Output clamped to `[0.0, 1.0]` (INV-8).
- Formula: `decay_score = base_relevance * boost_factor * exp(-age_days / tau)`

#### `async DecayEngine.run_decay_pass(session: AsyncSession, tenant_id: str, now: Optional[datetime] = None, batch_size: int = 10000) -> tuple[int, int]`
- Executes a bounded decay pass for a tenant.
- Returns `(fragments_updated, fragments_expired)`.
- Processes at most `batch_size` fragments per invocation (Phase 5).

#### `async DecayEngine.apply_near_miss_boost(session: AsyncSession, fragment_id: UUID, tenant_id: str) -> float`
- Applies a near-miss boost to a fragment.
- Increments `near_miss_count` (capped at `MAX_NEAR_MISS_BOOST_COUNT`).
- Does NOT modify `base_relevance` (Audit §2.2 fix).
- Returns new decay score.

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `DECAY_TAU` | dict | Source-type decay time constants (LLD §5 table) |
| `DECAY_TAU["TICKET_TEXT"]` | 270.0 | Ticket text tau |
| `DECAY_TAU["ALARM"]` | 90.0 | Alarm tau |
| `DECAY_TAU["TELEMETRY_EVENT"]` | 60.0 | Telemetry event tau |
| `DECAY_TAU["CLI_OUTPUT"]` | 180.0 | CLI output tau |
| `DECAY_TAU["CHANGE_RECORD"]` | 365.0 | Change record tau |
| `DECAY_TAU["CMDB_DELTA"]` | 90.0 | CMDB delta tau |
| `MAX_NEAR_MISS_BOOST_COUNT` | 10 | Max near-misses that contribute to boost |
| `BOOST_PER_NEAR_MISS` | 0.05 | Additive per near-miss |
| `MAX_BOOST_FACTOR` | 1.5 | Hard cap: 1.0 + 10 * 0.05 = 1.5 |
| `STALE_THRESHOLD` | 0.15 | Stale status threshold |
| `EXPIRATION_THRESHOLD` | 0.10 | Expiration status threshold |
| `MAX_IDLE_DAYS` | 90 | INV-6: force expiration after 90 days idle |

### DB Tables Touched

- `AbeyanceFragmentORM` (read, write)
  - Fields read: `tenant_id`, `snap_status`, `current_decay_score`, `event_timestamp`, `created_at`, `base_relevance`, `near_miss_count`, `source_type`, `updated_at`, `max_lifetime_days`
  - Fields written: `current_decay_score`, `snap_status`, `updated_at`, `near_miss_count`

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.models.abeyance_orm`: `AbeyanceFragmentORM`, `VALID_TRANSITIONS`
  - `backend.app.services.abeyance.events`: `FragmentStateChange`, `ProvenanceLogger`, `RedisNotifier`

### TODO/FIXME Comments

None found.

### Invariants Enforced

- **INV-2:** Decay is strictly monotonic decreasing under constant conditions
- **INV-3:** All scoring in bounded domains
- **INV-6:** Hard lifetime (730 days) and idle duration (90 days) bounds
- **INV-7:** Tenant isolation verification
- **INV-8:** No output outside `[0.0, 1.0]`
- **INV-10:** Full provenance via `ProvenanceLogger`
- **INV-12:** Redis notification after PostgreSQL persist

### Remediation Targets (Post-Audit)

- **Audit §2.2:** Unbounded relevance boosting → capped at 1.5 total
- **Audit §7.2:** No decay audit trail → append-only fragment_history via `ProvenanceLogger`

---

## 2. maintenance.py

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/maintenance.py`

### Public Methods with Signatures

#### `MaintenanceService.__init__(decay_engine: DecayEngine, accumulation_graph: AccumulationGraph, provenance: ProvenanceLogger)`
- Initializes maintenance service with dependencies.

#### `async MaintenanceService.run_decay_pass(session: AsyncSession, tenant_id: str) -> dict`
- Executes bounded decay pass. Max `MAX_DECAY_BATCH` fragments.
- Returns dict: `{"updated": int, "expired": int}`

#### `async MaintenanceService.prune_stale_edges(session: AsyncSession, tenant_id: str) -> int`
- Removes accumulation edges where both fragments have low decay scores.
- Returns count of edges removed.

#### `async MaintenanceService.expire_stale_fragments(session: AsyncSession, tenant_id: str) -> int`
- Transitions STALE fragments to EXPIRED. Max `MAX_PRUNE_BATCH`.
- Returns count of fragments expired.

#### `async MaintenanceService.cleanup_orphaned_entity_refs(session: AsyncSession, tenant_id: str) -> int`
- Removes entity refs pointing to non-existent fragments.
- Returns count of orphans cleaned.

#### `async MaintenanceService.run_full_maintenance(session: AsyncSession, tenant_id: str) -> dict`
- Executes all maintenance tasks in sequence.
- Returns dict with keys: `decay`, `stale_edges_pruned`, `fragments_expired`, `orphans_cleaned`

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_DECAY_BATCH` | 10,000 | Decay pass batch size |
| `MAX_ARCHIVE_BATCH` | 5,000 | Archive batch size |
| `MAX_PRUNE_BATCH` | 10,000 | Pruning batch size |
| `STALE_EDGE_THRESHOLD` | 0.2 | Stale edge decay score threshold |

### DB Tables Touched

- `AbeyanceFragmentORM` (read, write)
  - Fields: `tenant_id`, `id`, `snap_status`, `current_decay_score`, `updated_at`
- `AccumulationEdgeORM` (read, delete)
  - Fields: `tenant_id`, `fragment_a_id`, `fragment_b_id`
- `FragmentEntityRefORM` (read, delete)
  - Fields: `tenant_id`, `id`, `fragment_id`

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.services.abeyance.decay_engine`: `DecayEngine`
  - `backend.app.services.abeyance.accumulation_graph`: `AccumulationGraph`
  - `backend.app.services.abeyance.events`: `ProvenanceLogger`, `FragmentStateChange`

### TODO/FIXME Comments

None found.

---

## 3. telemetry_aligner.py

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/telemetry_aligner.py`

### Data Classes

#### `AnomalyFinding`
Structured anomaly event for telemetry alignment.
- Fields: `entity_id`, `tenant_id`, `domain`, `kpi_name`, `value` (float), `z_score` (float), `timestamp` (datetime), `affected_metrics` (list), `neighbour_count` (int), `neighbour_summary` (str), `metadata` (dict)

### Public Methods with Signatures

#### `TelemetryAligner.__init__(embedding_service=None)`
- Initializes with optional embedding service.
- Falls back to hash-based embedding in offline/test mode.

#### `TelemetryAligner.anomaly_to_text(anomaly: AnomalyFinding) -> str`
- Generates natural language description from anomaly event.
- Uses template from spec §4.

#### `TelemetryAligner.embed_anomaly(anomaly: AnomalyFinding) -> np.ndarray`
- Converts anomaly to embedding.
- If embedding_service available, uses it.
- Falls back to deterministic hash-based vector.

#### `TelemetryAligner._hash_embedding(text: str, dim: int = 64) -> np.ndarray`
- Deterministic hash-based embedding for offline/test mode (dim=64).

#### `TelemetryAligner.store_anomaly_fragment(anomaly: AnomalyFinding, storage=None) -> AbeyanceFragment`
- Creates and optionally stores a telemetry AbeyanceFragment.
- Returns `AbeyanceFragment` with `modality='telemetry'`.

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `_TELEMETRY_TEMPLATE` | (string) | Telemetry-to-text template from spec §4 |

### DB Tables Touched

- None directly (uses `AbeyanceColdStorage` if storage provided).

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.services.abeyance.cold_storage`: `AbeyanceFragment`

### TODO/FIXME Comments

None found.

### Special Notes

- Multi-modal matching: converts structured telemetry to natural language, embeds with same model as text fragments.
- Allows cross-modal similarity search (telemetry ↔ text).

---

## 4. incident_reconstruction.py

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/incident_reconstruction.py`

### Public Methods with Signatures

#### `async IncidentReconstructionService.reconstruct(session: AsyncSession, tenant_id: str, hypothesis_id: Optional[UUID] = None, entity_identifier: Optional[str] = None, time_start: Optional[datetime] = None, time_end: Optional[datetime] = None) -> dict`
- Assembles a time-ordered reconstruction of fragments and snaps.
- Can filter by:
  - `hypothesis_id` (for snap-based reconstruction)
  - `entity_identifier` (for entity-based reconstruction)
  - Time range (`time_start`, `time_end`)
- Returns dict with keys: `tenant_id`, `hypothesis_id`, `entity_identifier`, `fragment_count`, `snap_decision_count`, `timeline`
- Timeline entries include: `type`, `timestamp`, `fragment_id`, `source_type`, `summary`, `entities`, `status`, `score`, `failure_mode`, `threshold`, `detail`

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| Fragment limit | 100 | Max fragments in single query |
| Snap decision limit | 200 | Max snap decisions in single query |
| History records limit | 500 | Max history records in single query |

### DB Tables Touched

- `AbeyanceFragmentORM` (read)
  - Fields: `tenant_id`, `id`, `event_timestamp`, `snapped_hypothesis_id`, `source_type`, `raw_content`, `extracted_entities`, `snap_status`
- `FragmentEntityRefORM` (read)
  - Fields: `tenant_id`, `fragment_id`, `entity_identifier`
- `SnapDecisionRecordORM` (read)
  - Fields: `tenant_id`, `new_fragment_id`, `candidate_fragment_id`, `evaluated_at`, `decision`, `final_score`, `failure_mode_profile`, `threshold_applied`
- `FragmentHistoryORM` (read)
  - Fields: `tenant_id`, `fragment_id`, `event_timestamp`, `event_type`, `event_detail`

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.models.abeyance_orm`: Multiple ORM classes

### TODO/FIXME Comments

None found.

### Special Notes

- Uses provenance logs (fragment_history, snap_decision_record, cluster_snapshot) to assemble causal narrative.
- Designed for operator forensics.
- Timeline automatically sorted by timestamp.

---

## 5. value_attribution.py

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/value_attribution.py`

### Public Methods with Signatures

#### `async ValueAttributionService.record_discovery(session: AsyncSession, tenant_id: str, hypothesis_id: UUID, discovery_type: str, discovered_entities: list[str], discovered_relationships: list[str], confidence: float) -> UUID`
- Creates permanent ledger entry for a validated discovery.
- Returns entry ID.

#### `async ValueAttributionService.record_value_event(session: AsyncSession, tenant_id: str, ledger_entry_id: UUID, event_type: str, attributed_hours: Optional[float] = None, attributed_currency: Optional[float] = None, rationale: str = "", detail: Optional[dict] = None) -> UUID`
- Records a value realization event.
- Returns event ID.

#### `async ValueAttributionService.get_value_report(session: AsyncSession, tenant_id: str, period_start: Optional[datetime] = None, period_end: Optional[datetime] = None) -> dict`
- Generates value attribution report for a period.
- Returns dict with keys: `tenant_id`, `total_discoveries`, `discovery_breakdown` (by type), `mttr_hours_saved`, `currency_saved`

#### `async ValueAttributionService.compute_illumination_ratio(session: AsyncSession, tenant_id: str, total_incidents: int) -> dict`
- Computes illumination ratio (LLD §13 Rule 5).
- Formula: `illumination_ratio = incidents_involving_pedkai_entities / total_incidents`
- Returns dict with keys: `tenant_id`, `ratio`, `incidents_with_pedkai_entities`, `total_incidents`, `active_discoveries`

#### `async ValueAttributionService.compute_dark_graph_index(session: AsyncSession, tenant_id: str, baseline_divergences: Optional[int] = None) -> dict`
- Dark Graph Reduction Index (LLD §13 Rule 6).
- Formula: `dark_graph_reduction = 1 - (current_divergences / baseline_divergences)`
- Baseline must come from initial deployment measurement — NOT fabricated (Audit §10 fix).
- Returns dict with keys: `tenant_id`, `index`, `current_divergences`, `baseline_divergences`, `resolved_by_pedkai`, `status`, `message` (if baseline unavailable)

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| Reference tag format | `PEDKAI-{tenant[:8]}-{hypothesis[:8]}` | CMDB reference identifier |

### DB Tables Touched

- `DiscoveryLedgerORM` (read, write)
  - Fields: `id`, `tenant_id`, `hypothesis_id`, `discovery_type`, `discovered_entities`, `discovered_relationships`, `cmdb_reference_tag`, `discovery_confidence`, `status`, `discovered_at`
- `ValueEventORM` (read, write)
  - Fields: `id`, `tenant_id`, `ledger_entry_id`, `event_type`, `attributed_value_hours`, `attributed_value_currency`, `attribution_rationale`, `event_detail`, `event_at`

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.models.abeyance_orm`: `DiscoveryLedgerORM`, `ValueEventORM`

### TODO/FIXME Comments

None found.

### Audit Notes

- Implements LLD §13 structurally sound (Audit §10 #6).
- Minor fix: `baseline_divergences` no longer fabricated (Audit §10 table).

---

## 6. abeyance_decay.py (DEPRECATED)

**Path:** `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance_decay.py`

### Deprecation Status

**DEPRECATED** — Old Abeyance Memory decay scoring service.

**Replacement:** `backend.app.services.abeyance.decay_engine.DecayEngine`

**Kept solely for:** Backward compatibility with `tests/test_abeyance_decay.py`

### Reason for Deprecation

This module operated on `DecisionTraceORM` (split-brain architecture, Audit §3.1).
Superseded by `DecayEngine` which operates on `AbeyanceFragmentORM` with:
- Source-type-dependent time constants (not a single global lambda)
- Bounded near-miss boost (capped at 1.5x, not unbounded 1.15^n)
- Monotonic decay enforcement (new_score <= old_score)
- Hard lifetime (730 days) and idle timeout (90 days)
- Full provenance via `ProvenanceLogger` (INV-10)

### Public Methods with Signatures

#### `AbeyanceDecayService.__init__(decay_lambda: Optional[float] = None)`
- Initializes with optional decay lambda.
- Defaults to `settings.abeyance_decay_lambda`.

#### `AbeyanceDecayService.compute_decay(days_since_created: float, corroboration_count: int = 0) -> float`
- Returns decay score for a fragment of the given age.
- Formula: `raw = 1.0 * exp(-lambda * days_since_created) * (1.0 + 0.3 * corroboration_count)`
- Clamped to `[0.0, 1.0]`

#### `AbeyanceDecayService._days_since(created_at: datetime) -> float`
- Returns fractional days between `created_at` and now (UTC).

#### `AbeyanceDecayService.run_decay_pass(tenant_id: str, session: Session) -> dict`
- Recomputes and persists `decay_score` for all ACTIVE fragments of a tenant.
- Returns dict: `{"updated": int}`

#### `AbeyanceDecayService.mark_stale_fragments(tenant_id: str, session: Session, threshold: float = 0.05) -> int`
- Transitions fragments with `decay_score` below threshold to status='STALE'.
- Returns count of marked fragments.

### Constants/Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `_BASE_RELEVANCE` | 1.0 | Base relevance score |
| `_CORROBORATION_WEIGHT` | 0.3 | Weight per corroboration |
| `_DEFAULT_STALE_THRESHOLD` | 0.05 | Default stale threshold |

### DB Tables Touched

- `DecisionTraceORM` (read, write)
  - Fields: `tenant_id`, `abeyance_status`, `decay_score`, `created_at`, `corroboration_count`

### Dependencies on Other Abeyance Files

- Imports:
  - `backend.app.models.decision_trace_orm`: `DecisionTraceORM`
  - `backend.app.core.config`: `get_settings`

### TODO/FIXME Comments

None found.

### Import Analysis (Safety for Removal)

**Current imports:**
- **Tests:** `tests/test_abeyance_decay.py` (only place that imports `AbeyanceDecayService`)
- **Config references:** `backend/app/core/config.py` defines `abeyance_decay_interval_hours` and `abeyance_decay_lambda` (used by deprecated module)
- **Alembic migration:** `backend/alembic/versions/008_abeyance_decay.py` (migration revision ID, not a runtime import)
- **Alembic chain:** `backend/alembic/versions/009_create_customers_tables.py` references `down_revision: '008_abeyance_decay'`

**Safe to remove if:**
1. `tests/test_abeyance_decay.py` is deleted or migrated to test new `DecayEngine`
2. Config entries `abeyance_decay_interval_hours` and `abeyance_decay_lambda` are removed from settings
3. Alembic migration chain is updated to skip migration 008

**Risk level:** LOW (isolated to tests; no production code imports it)

**Recommendation:** Safe for removal once test suite is migrated to `DecayEngine`.

---

## Summary Table

| Subsystem | Type | Status | Lines | Key Responsibility |
|-----------|------|--------|-------|-------------------|
| `decay_engine.py` | Core | Active | 283 | Compute and apply exponential decay with bounded boost |
| `maintenance.py` | Support | Active | 190 | Bounded background jobs: decay pass, edge pruning, orphan cleanup |
| `telemetry_aligner.py` | Support | Active | 145 | Convert anomalies to text, embed, store as fragments (multi-modal) |
| `incident_reconstruction.py` | Support | Active | 162 | Assemble incident timelines from provenance logs |
| `value_attribution.py` | Support | Active | 215 | Track operational value of discoveries, compute KPIs |
| `abeyance_decay.py` | Support | **DEPRECATED** | 138 | Old decay service (split-brain, replaced by `decay_engine`) |

---

## Cross-Subsystem Dependencies

```
decay_engine
  ← maintenance (uses run_decay_pass)
  → ProvenanceLogger (events module)
  → RedisNotifier (events module)
  → AbeyanceFragmentORM

maintenance
  → decay_engine
  → accumulation_graph
  → ProvenanceLogger
  → {AbeyanceFragmentORM, AccumulationEdgeORM, FragmentEntityRefORM, FragmentHistoryORM}

telemetry_aligner
  → cold_storage (AbeyanceFragment class)
  → np/numpy (embedding vectors)

incident_reconstruction
  → {AbeyanceFragmentORM, FragmentEntityRefORM, SnapDecisionRecordORM, FragmentHistoryORM, ClusterSnapshotORM}

value_attribution
  → {DiscoveryLedgerORM, ValueEventORM}

abeyance_decay (DEPRECATED)
  → DecisionTraceORM (old ORM)
  → settings.abeyance_decay_lambda
```

---

## Compliance Notes

- All subsystems follow INV-2 (monotonicity), INV-3 (bounded domains), INV-6 (lifetime/idle bounds), INV-7 (tenant isolation), INV-8 (output bounds), INV-10 (provenance).
- Phase 5 implementation: all batch operations have configurable limits.
- Audit §2.2 (boost capping): enforced in `decay_engine`.
- Audit §7.2 (decay audit trail): implemented via `ProvenanceLogger` in `decay_engine`.
- Audit §10 (discovery ledger): value_attribution no longer fabricates baseline divergences.
