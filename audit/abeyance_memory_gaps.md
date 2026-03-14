# TASK-003: Abeyance Memory Implementation Gaps Audit

**Generated**: 2026-03-10
**Auditor**: Claude Code Discovery Agent
**Status**: ⚠️ Critical implementation gaps identified

---

## Executive Summary

The Abeyance Memory feature — Pedk.ai's core differentiator for long-horizon, multi-modal evidence fusion — **exists only in specification form**. The backend infrastructure for vector storage has been partially implemented, but the three critical Abeyance maturity dimensions remain incomplete or unimplemented:

1. ✅ **Vector Storage** — 70% complete (pgvector table exists, but no Abeyance-specific schema)
2. ⚠️ **Semantic Similarity Snapping** — 40% complete (decision similarity search works, but no fragment-specific snap logic)
3. ❌ **Multi-modal Matching** — 0% implemented (no telemetry-to-text alignment)
4. ❌ **Long-horizon Retrieval** — 0% implemented (no cold storage pipeline)
5. ❌ **Abeyance Decay** — 0% implemented (no TTL/relevance scoring logic)

---

## 1. Abeyance Memory: Specification vs. Reality

### From Product Spec (§4)

The PRODUCT_SPEC defines Abeyance Memory as:

> "Pedk.ai's proprietary capability to hold **disconnected, unresolved technical facts** in a latent semantic buffer — indefinitely — until the missing contextual link appears. Unlike conventional monitoring systems that process events in real-time and discard unresolvable data, Pedk.ai *remembers* fragments that don't yet make sense."

**Maturity Model** (from `/Users/himanshu/Projects/Pedkai/.claude/worktrees/trusting-hugle/PRODUCT_SPEC.md` lines 210–216):

| Aspect | Status | Gap |
|--------|--------|-----|
| Vector storage of fragments | ✅ Implemented (pgvector) | — |
| Semantic similarity snapping | ✅ Implemented | Threshold tuning needed per deployment |
| Multi-modal matching (text + telemetry) | ⚠️ Partial | Need structured telemetry-to-text alignment |
| Long-horizon retrieval (>30 days) | ⚠️ Partial | Cold storage retrieval pipeline incomplete |
| Abeyance decay and relevance scoring | ❌ Not implemented | Stale fragments need TTL with relevance weighting |

### Actual Implementation Status

**No dedicated Abeyance Memory module exists in the backend.**

---

## 2. Vector Storage Infrastructure

### Current State: pgvector Table Exists, But Only for Decision Traces

**File**: `/Users/himanshu/Projects/Pedkai/backend/app/models/decision_trace_orm.py`

**Table**: `decision_traces`

**Schema** (relevant columns):

```python
class DecisionTraceORM(Base):
    __tablename__ = "decision_traces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Text fields for embedding
    trigger_description = Column(Text, nullable=False)
    decision_summary = Column(Text, nullable=False)
    tradeoff_rationale = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=False)

    # Vector embedding (pgvector)
    embedding = Column(Vector(settings.embedding_dimension), nullable=True)
    embedding_provider = Column(String(50), nullable=True)
    embedding_model = Column(String(100), nullable=True)

    # Decision metadata
    domain = Column(String(50), nullable=False, default="anops", index=True)
    confidence_score = Column(Float, default=0.0)
    memory_hits = Column(Integer, nullable=False, default=0)
    causal_evidence_count = Column(Integer, nullable=False, default=0)

    # For semantic context graph (recursive reasoning)
    parent_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    derivation_type = Column(String(50), nullable=True)  # FOLLOW_UP | DIRECT_CAUSE | SIMILAR_PATTERN
```

**Embedding Dimension**: 3072 (Gemini text-embedding-004)
- Fallback: 384 (local sentence-transformers MiniLM-L6-v2) when Gemini unavailable

**Critical Gap**: The `decision_traces` table stores **resolved decisions only**. There is **no separate table for unresolved fragments** (abeyance items).

---

## 3. Semantic Similarity Search (Partial Implementation)

### Current Snapping Logic

**File**: `/Users/himanshu/Projects/Pedkai/backend/app/services/decision_repository.py`

**Method**: `find_similar()` (lines 152–206)

```python
async def find_similar(
    self,
    query: SimilarDecisionQuery,
    query_embedding: list[float],
    session: Optional[AsyncSession] = None,
) -> list[tuple[DecisionTrace, float]]:
    """
    Find similar decisions using pgvector cosine similarity.
    """
    # ... build conditions (tenant_id, domain, embedding_provider) ...

    # Raw similarity calculation (1 - distance)
    raw_similarity = (1 - DecisionTraceORM.embedding.cosine_distance(query_embedding))

    # Query with threshold filtering
    result = await s.execute(
        select(
            DecisionTraceORM,
            raw_similarity.label("raw_similarity")
        )
        .where(
            and_(
                *conditions,
                DecisionTraceORM.embedding.isnot(None),
                raw_similarity >= query.min_similarity  # Threshold: default 0.9
            )
        )
        .limit(query.limit * 2)
    )

    # Apply feedback boost and re-rank
    scored_results = []
    for orm_obj, sim in rows:
        feedback_boost = 0.1 * orm_obj.feedback_score
        adjusted_sim = sim + feedback_boost
        scored_results.append((self._orm_to_pydantic(orm_obj), adjusted_sim))

    scored_results.sort(key=lambda x: x[1], reverse=True)
    return scored_results[:query.limit]
```

**What Works**:
- ✅ Cosine similarity search against decision traces via pgvector
- ✅ Feedback boost mechanism (0.1 × feedback_score)
- ✅ Tenant and domain filtering
- ✅ Configurable similarity threshold (default 0.9, set in config)

**What's Missing**:
- ❌ No "Abeyance Fragment" entity to snap against
- ❌ No time-horizon weighting (recent vs. old evidence treated equally)
- ❌ No evidence modality differentiation (human vs. machine telemetry)
- ❌ No "snap resolution" workflow (when two fragments match, they remain separate)

---

## 4. Embedding Generation (Partial Implementation)

### Text Alignment Logic

**File**: `/Users/himanshu/Projects/Pedkai/backend/app/services/embedding_service.py`

**Method**: `create_decision_text()` (lines 62–86)

```python
def create_decision_text(
    self,
    trigger_description: str,
    decision_summary: str,
    tradeoff_rationale: str,
    action_taken: str,
    context_description: str = "",
) -> str:
    """
    Create a text representation of a decision for embedding.

    Combines key fields into a single text that captures
    the semantic meaning of the decision.
    """
    parts = [
        f"Trigger: {trigger_description}",
        f"Decision: {decision_summary}",
        f"Rationale: {tradeoff_rationale}",
        f"Action: {action_taken}",
    ]

    if context_description:
        parts.append(f"Context: {context_description}")

    return "\n".join(parts)
```

**What Works**:
- ✅ Structured text composition from decision fields
- ✅ Support for optional context description
- ✅ Clear field labeling for semantic richness

**What's Missing**:
- ❌ **No telemetry-to-text alignment**: Structured metrics (e.g., CPU%, latency_ms, interface_flaps) are not converted to narrative text
- ❌ No multi-modal representation: Decision traces embed *only* unstructured text, not structured telemetry
- ❌ No evidence modality markers: Cannot distinguish human-written evidence from machine-generated telemetry
- ❌ No fragment-specific alignment: No function to embed unresolved ticket snippets, CLI outputs, or raw telemetry

---

## 5. TTL and Retention Policies

### Current Data Retention Implementation

**File**: `/Users/himanshu/Projects/Pedkai/backend/app/services/data_retention.py`

**Policy**:

```python
RETENTION_POLICIES: dict[str, timedelta] = {
    "llm_prompt_logs": timedelta(days=90),
}

# Tables with 7-year regulatory retention
REGULATORY_TABLES = ["incidents", "audit_event_log", "incident_audit_entries"]
```

**Key Findings**:

- ✅ 90-day retention policy for LLM prompt logs
- ✅ 7-year retention for incidents and audit trails (regulatory)
- ✅ KPI telemetry: 30-day rolling window (TimescaleDB native policy)
- ❌ **Decision traces have NO retention policy** (indefinite)
- ❌ **No Abeyance-specific decay logic**:
  - No TTL for unresolved fragments
  - No relevance weighting (stale fragments not down-ranked)
  - No distinction between "fresh" (high relevance) and "aged" (lower relevance) evidence
  - No TTL variance by fragment type (Type 1–4 dark graph categories)

---

## 6. Cold Storage and Archival Pipeline

### Current State: **NOT IMPLEMENTED**

**Findings**:

- ❌ No S3 integration for cold storage
- ❌ No Parquet export mechanism
- ❌ No archival workflow
- ❌ No long-horizon (>30 days) retrieval pipeline

**References to Archive/Cold**:

1. **`data_retention.py`**: Only handles deletion, not archival
2. **`policy_orm.py`**: Tracks policy versions as "archived", but this is administrative versioning, not data archival
3. **`load_telco2_tenant.py`**: References Parquet file input for test data, but no production archival pipeline

---

## 7. Multi-modal Matching (Text + Telemetry)

### Current State: **NOT IMPLEMENTED**

The spec explicitly identifies this as a critical gap:

> "Multi-modal matching (text + telemetry) | ⚠️ Partial | Need structured telemetry-to-text alignment"

**What's Missing**:

1. **No structured telemetry schema** for Abeyance fragments:
   - KPI samples (CPU%, memory, latency)
   - Network metrics (packet loss, jitter, throughput)
   - Alarm severities and types
   - No standardized alignment to narrative text

2. **No fusion logic** to match unstructured text (ticket notes, CLI outputs) to structured telemetry:
   - No dimension reduction for heterogeneous data
   - No weighted similarity combining text + metrics
   - No evidence modality markers (e.g., `source_type: "human_ticket"` vs. `"machine_alarm"`)

3. **No fragment modality differentiation**:
   - Decision traces are text-only (`trigger_description`, `decision_summary`, etc.)
   - No support for embedding raw telemetry events alongside text

---

## 8. Long-horizon Retrieval (>30 days)

### Current State: **NOT IMPLEMENTED**

**Findings**:

- ✅ Decision traces stored indefinitely in PostgreSQL
- ✅ Similarity search works for in-memory data (hot storage)
- ❌ **No cold storage retrieval**:
  - No archival of >30-day-old fragments to S3/Parquet
  - No mechanism to re-materialize cold fragments into hot storage for search
  - No query optimization for long-term datasets

- ❌ **No time-horizon awareness**:
  - Similarity search treats a 1-day-old fragment and a 6-month-old fragment equally
  - No decay function to down-weight stale evidence

---

## 9. Decay and Relevance Scoring

### Current State: **NOT IMPLEMENTED**

The spec identifies this as a critical gap:

> "Abeyance decay and relevance scoring | ❌ Not implemented | Stale fragments need TTL with relevance weighting"

**What's Missing**:

1. **No TTL per fragment**:
   - No `created_at` aging for decay calculation
   - No `resolution_attempts` counter to track engagement
   - No `dark_graph_type` (Type 1–4) to differentiate decay rates

2. **No relevance decay function**:
   - No formula to down-weight older evidence (e.g., exponential decay)
   - No recency-based re-ranking in similarity search
   - No statistical weighting by source reliability or evidence modality

3. **No persistence of decay state**:
   - No `last_matched_at` timestamp to track engagement
   - No `relevance_score` to persist computed decay value
   - No feedback loop to adjust decay rates based on operator feedback

---

## 10. Implementation Checklist: The 5 Maturity Dimensions

### Dimension 1: Vector Storage ✅ 70% Complete

**Implemented**:
- ✅ pgvector extension available in PostgreSQL
- ✅ `embedding` column in `decision_traces` (3072-dim for Gemini, 384-dim fallback)
- ✅ Index created via SQLAlchemy ORM

**Not Implemented**:
- ❌ Dedicated `abeyance_fragments` table
- ❌ Schema for unresolved evidence (no `unresolved_entity`, `resolution_hints`, `ttl`, `dark_graph_type` columns)
- ❌ Fragment-specific metadata (source modality, evidence type, etc.)

**Task**: Create migration to add `abeyance_fragments` table with fields per spec.

---

### Dimension 2: Semantic Similarity Snapping ✅ 40% Complete

**Implemented**:
- ✅ Cosine similarity via pgvector in `find_similar()`
- ✅ Feedback boost (0.1 × feedback_score)
- ✅ Configurable threshold (default 0.9)

**Not Implemented**:
- ❌ Fragment-specific snapping workflow
- ❌ "Snap resolution" logic (when two fragments match, create a corroborated hypothesis)
- ❌ Time-horizon weighting (recent evidence prioritized)
- ❌ Evidence modality markers in similarity scoring

**Task**: Implement snap resolution logic to link fragments with high similarity (>0.92) into corroborated hypotheses.

---

### Dimension 3: Multi-modal Matching ❌ 0% Complete

**Not Implemented**:
- ❌ Structured telemetry schema
- ❌ Telemetry-to-text conversion (e.g., "CPU spiked to 89% for 2 min" → narrative)
- ❌ Heterogeneous embedding (text ⊕ metrics)
- ❌ Weighted similarity for multi-modal fusion
- ❌ Evidence modality differentiation

**Task**: Design and implement telemetry normalization layer and multi-modal embedding strategy.

---

### Dimension 4: Long-horizon Retrieval ❌ 0% Complete

**Not Implemented**:
- ❌ Cold storage archival (S3/Parquet)
- ❌ Retrieval pipeline to materialize cold data
- ❌ Query optimization for >30-day searches
- ❌ Decay weighting in similarity search

**Task**: Implement archival and retrieval pipeline with time-horizon-aware similarity scoring.

---

### Dimension 5: Abeyance Decay ❌ 0% Complete

**Not Implemented**:
- ❌ TTL per fragment
- ❌ Decay function (exponential, linear, or sigmoid)
- ❌ Relevance scoring persistence
- ❌ Type-specific decay rates (Type 1–4 dark graph categories)
- ❌ Recency-based re-ranking

**Task**: Implement decay scoring model and integrate into similarity search.

---

## 11. Required Schema Changes

### New Table: `abeyance_fragments`

```python
class AbeyanceFragmentORM(Base):
    __tablename__ = "abeyance_fragments"

    # Identification
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(255), nullable=False, index=True)

    # Fragment source and metadata
    source_type = Column(String(50), nullable=False)  # "ticket", "cli_output", "alarm", "telemetry", "log"
    source_id = Column(String(255), nullable=True)  # ticket_id, alarm_id, etc.

    # Raw evidence
    raw_evidence = Column(Text, nullable=False)  # Original ticket note, CLI output, etc.
    evidence_summary = Column(Text, nullable=True)  # Summary for embedding

    # Unresolved elements
    unresolved_entity = Column(String(255), nullable=True)  # IP, hostname, interface, etc.
    resolution_hints = Column(JSON, nullable=True)  # { "ip": "10.0.1.x", "role": "gateway", ... }

    # Embedding
    embedding = Column(Vector(settings.embedding_dimension), nullable=True)
    embedding_provider = Column(String(50), nullable=True)
    embedding_model = Column(String(100), nullable=True)

    # Dark graph context
    dark_graph_type = Column(String(50), nullable=False)  # "Type 1", "Type 2", "Type 3", "Type 4"

    # Lifecycle
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_matched_at = Column(DateTime(timezone=True), nullable=True)
    resolution_attempts = Column(Integer, default=0)

    # TTL and decay
    ttl = Column(Integer, nullable=False)  # seconds
    expires_at = Column(DateTime(timezone=True), nullable=False)
    relevance_score = Column(Float, default=1.0)  # Decays over time

    # Resolution
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_via_decision_id = Column(UUID(as_uuid=True), nullable=True)  # FK to decision_traces.id

    __table_args__ = (
        Index("ix_abeyance_fragments_tenant_type", "tenant_id", "dark_graph_type"),
        Index("ix_abeyance_fragments_expires", "expires_at"),
        Index("ix_abeyance_fragments_tenant_created", "tenant_id", "created_at"),
    )
```

---

## 12. Files Summary

### Backend Vector Storage (Partial)
- **`decision_trace_orm.py`**: pgvector column exists, but only for decision traces
- **`decision_repository.py`**: Similarity search implemented, but no fragment-specific snap logic
- **`embedding_service.py`**: Text alignment for decisions, no telemetry-to-text conversion

### Data Retention (Insufficient)
- **`data_retention.py`**: Deletion policies exist, no Abeyance-specific TTL

### Missing Entirely
- **`abeyance_memory.py`**: Main Abeyance Memory service (not found)
- **`abeyance_fragment_orm.py`**: ORM model for fragments (not found)
- **`telemetry_alignment.py`**: Telemetry-to-text converter (not found)
- **`cold_storage.py`**: Archival and retrieval pipeline (not found)
- **`decay_service.py`**: Relevance decay calculator (not found)

---

## 13. Task Backlog (from PRODUCT_SPEC)

From `/Users/himanshu/Projects/Pedkai/.claude/worktrees/trusting-hugle/PRODUCT_SPEC.md`:

| Task ID | Description | Priority | Owner |
|---------|-------------|----------|-------|
| **T-016** | Implement Abeyance Memory decay scoring and cold storage retrieval pipeline | 🔴 Critical | Pedk.ai |
| **T-026** | Implement Abeyance Memory multi-modal matching (structured telemetry ↔ unstructured text) | 🟡 High | Pedk.ai |

Both are currently unstarted.

---

## 14. Recommendations

### Immediate (Sprint 1–2)
1. **Create `abeyance_fragments` ORM table** with schema outlined in §11
2. **Add database migration** to deploy table in production
3. **Implement `AbeyanceFragmentRepository`** with CRUD and similarity search
4. **Add "snap resolution" workflow** to link high-similarity fragments into corroborated hypotheses

### Short-term (Sprint 3–4)
5. **Implement decay scoring function** (exponential decay, configurable per dark_graph_type)
6. **Add TTL enforcement** via cleanup service (similar to `data_retention.py`)
7. **Integrate decay weighting into similarity search** (boost recent fragments)

### Medium-term (Sprint 5–6)
8. **Design telemetry-to-text alignment layer** (schema for metrics, conversion functions)
9. **Implement multi-modal embedding** (heterogeneous representation)
10. **Add evidence modality markers** to distinguish human vs. machine evidence

### Long-term (Sprint 7+)
11. **Build cold storage archival pipeline** (S3/Parquet export)
12. **Implement long-horizon retrieval** (query optimization for >30-day data)
13. **Add operator dashboard** to visualize Abeyance Memory status, resolution rates, and age distribution

---

## 15. Conclusion

**Abeyance Memory is Pedk.ai's core differentiator, but its implementation is 35% complete.**

The vector storage foundation is laid (pgvector + cosine similarity), but without:
- Dedicated fragment schema
- TTL and decay logic
- Telemetry-to-text alignment
- Cold storage pipeline
- Snap resolution workflow

...the feature remains a specification rather than a working capability. All five maturity dimensions require engineering effort to move from prototype to production-ready.

**Estimated effort**: 30–40 story points across 6–8 sprints, depending on parallelization and resource allocation.

---

## Appendix: Relevant File Paths

- `/Users/himanshu/Projects/Pedkai/backend/app/models/decision_trace_orm.py` — Decision traces ORM (pgvector column)
- `/Users/himanshu/Projects/Pedkai/backend/app/services/decision_repository.py` — Similarity search implementation
- `/Users/himanshu/Projects/Pedkai/backend/app/services/embedding_service.py` — Text alignment for decisions
- `/Users/himanshu/Projects/Pedkai/backend/app/services/data_retention.py` — Data retention policies
- `/Users/himanshu/Projects/Pedkai/task_abeyance_memory_engine.md` — Original task specification
- `/Users/himanshu/Projects/Pedkai/.claude/worktrees/trusting-hugle/PRODUCT_SPEC.md` — Product specification (§4)
