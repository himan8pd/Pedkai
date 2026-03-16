# Audit Findings Index - ABEYANCE_MEMORY_FORENSIC_AUDIT_V2.md

Extracted from sections 2-9 of the forensic audit document.
Generated: 2026-03-16

## Findings Table

| Finding ID | Severity | One-line Summary | Affected Subsystem | Root Cause | Classification |
|---|---|---|---|---|---|
| F-2.1 | Moderate | "Discovery" mechanism is similarity search, not reasoning or hypothesis formation | Snap Engine | Misleading marketing language masking true mechanical function (threshold comparison on cosine similarity) | architectural flaw |
| F-2.2 | Minor | Dormant fragment activation claimed as novel but is standard time-weighted nearest-neighbor search | Core Design | Unjustified novelty claims; mechanism already exists in anomaly detection and recommendation systems | architectural flaw |
| F-2.3 | Moderate | Accumulation graph correlation discount is a heuristic, not a statistical test | Accumulation Graph | Graph density used as proxy for correlation independence; cannot verify true independence from structure alone | architectural flaw |
| F-2.4 | Severe | Five weight profiles (DARK_EDGE, DARK_NODE, etc.) are hand-tuned with no empirical validation | Snap Engine | No A/B testing, sensitivity analysis, or documentation of how weights were derived | architectural flaw |
| F-3.1 | Severe | Shadow Topology service built but completely unused in snap engine | Shadow Topology, Snap Engine | Snap engine uses Jaccard*0.8 heuristic instead of proper BFS-based topological proximity | architectural flaw |
| F-3.2 | Critical | Enrichment chain passes empty entity list to topology expansion, making topo embedding 25% zeros | Enrichment Chain | Entity identifiers constructed but never passed to get_neighbourhood(); entity_ids always empty | code bug |
| F-3.3 | Severe | Telemetry aligner falls back to hash embeddings (removed in v2.0 design) in async production context | Telemetry Aligner | Loop.is_running() check always True in async FastAPI server; fallback activates every call in production | code bug |
| F-3.4 | Moderate | Dual cold storage paths (PostgreSQL + Parquet) with no synchronization or schema alignment | Cold Storage | Two independent backends with different schemas, dimensionalities, and silent error handling; no reconciliation mechanism | architectural flaw |
| F-3.5 | Minor | Deprecated abeyance_decay.py module emits DeprecationWarning on import; tests validate dead code | Testing | Module retained for backward compatibility but not actively used; deprecated tests should be removed | code bug |
| F-4.1 | Moderate | Temporal modifier diurnal component penalizes events at different times of day | Snap Engine | Assumes failure correlation peaks at matching time-of-day; invalid for hardware/config/vendor failures | architectural flaw |
| F-4.2 | Severe | Entity extraction is single point of failure; missing extraction causes permanent loss of fragment | Snap Engine | No fallback beyond telecom regex; fragments without extracted entities never reach snap evaluation and decay to zero silently | code bug |
| F-4.3 | Minor | Sidak correction assumes profile independence when profiles are actually correlated | Snap Engine | Five profiles share embedding components and entity overlaps; conservative bias acceptable but unexplained | architectural flaw |
| F-4.4 | Moderate | No negative evidence mechanism to mark fragments as irrelevant beyond time-based decay | Snap Engine | System can only corroborate or snap; no operator-driven reclassification or accelerated decay for investigated non-relevant evidence | missing feature |
| F-5.1 | Critical | LLM embedding cost makes system economically non-viable at upper operating range (10K events/min = $57.6K/day) | Enrichment Chain | Up to 4 LLM calls per fragment; no caching, batching, or tiered enrichment strategy in design | economic issue |
| F-5.2 | Severe | Accumulation graph loads all tenant edges into memory (up to 10M edges = ~2GB per tenant) | Accumulation Graph | Unbounded SELECT * without pagination; loads every edge ORM object for union-find | code bug |
| F-5.3 | Severe | Maintenance edge pruning executes N+1 queries (2 SELECTs per edge instead of single JOIN) | Maintenance | Loop over edges with individual fragment lookups; should be batch JOIN query | code bug |
| F-5.4 | Moderate | IVFFlat index list parameter fixed at 100; recall degrades as data grows (should scale with sqrt(n)) | Cold Storage | Weekly rebuild adjusts for count changes >20% but does not dynamically adjust list parameter | code bug |
| F-5.5 | Moderate | No connection pooling or rate limiting on LLM calls; burst of concurrent fragments triggers rate limiting | Enrichment Chain | Synchronous LLM calls in async context without pooling or circuit breaker; cascades to hash embedding fallback | architectural flaw |
| F-6.1 | Severe | LLM outage degenerates system to time-based correlation (75% embedding becomes zeros; only 16.7% temporal signal remains) | Snap Engine, Enrichment Chain | Embedding mask exists but snap engine does not consume it; scoring ignores validity | code bug |
| F-6.2 | Critical | Embedding mask stored but never read by snap engine; INV-11 violated in practice | Snap Engine | Mask computed during enrichment but not consulted during cosine similarity; full vector scored regardless of validity | code bug |
| F-6.3 | Moderate | Parquet cold storage silently swallows all errors during load with bare except clause | Cold Storage | No logging or alerting on corrupted files; operator cannot detect incomplete search results | code bug |
| F-6.4 | Moderate | Race condition in edge eviction allows concurrent snap evaluations to double-evict edges | Accumulation Graph | Edge limit enforcement lacks row-level locking; counts and evictions happen in separate queries | code bug |
| F-6.5 | Moderate | No idempotency on snap application; crash after fragment A transition leaves orphaned hypothesis_ids | Snap Engine | Write-ahead logs state change but recovery does not handle partial snap application | code bug |
| F-7.1 | Severe | No operational metrics (counters, histograms, gauges, latency tracking); only forensic observability exists | Observability | System provides post-hoc forensic capability but not real-time operational health assessment | missing feature |
| F-7.2 | Moderate | No alerting on anomalous snap rates; threshold miscalibration or embedding drift produces bad results silently | Observability | System silently produces floods of false positives or zeros false negatives without operator notification | missing feature |
| F-7.3 | Moderate | Maintenance job results are fire-and-forget; no maintenance history table or job tracking | Observability | Results returned but not persisted; operator cannot query historical decay/expiration rates | missing feature |
| F-8.1 | Critical | Embedding cost dominates at scale; no batch embedding, caching, tiered enrichment, or local model strategy | Enrichment Chain | Per-fragment LLM cost explodes at upper operating range; design specifies target rate without cost model | economic issue |
| F-8.2 | Moderate | Cold storage growth unbounded; 2 years at 10K events/min = 10.5B fragments with no expiration policy | Cold Storage | Fragments expire from hot after 730 days but move to cold with no retention limit or retirement date | architectural flaw |
| F-9.1 | Severe | Parquet path construction from tenant_id vulnerable to directory traversal (../../../etc/) | Cold Storage | No sanitization of tenant_id before path construction; rglob traversal would escape intended directory | code bug |
| F-9.2 | Moderate | Embedding vectors expose operational context; partial inversion possible per research; multi-tenant isolation at risk | Enrichment Chain | Raw embeddings exposed in cold storage and fragment API; if tenant isolation fails, adjacent tenant data inferrable | security issue |
| F-9.3 | Minor | CMDB export sanitization uses removal allowlist instead of inclusion safelist; fragile against future additions | Shadow Topology | Strips only specific fields (evidence_summary, confidence); retains attributes JSONB which may contain sensitive ops data | architectural flaw |

## Summary Statistics

- **Total Findings:** 31
- **Critical:** 5 (F-3.2, F-6.2, F-5.1, F-8.1, and one security finding implied in F-9.1)
- **Severe:** 12 (F-2.4, F-3.1, F-3.3, F-4.2, F-5.2, F-5.3, F-6.1, F-7.1, F-9.1)
- **Moderate:** 11 (F-2.1, F-2.3, F-4.1, F-4.4, F-5.4, F-5.5, F-6.3, F-6.4, F-6.5, F-7.2, F-7.3, F-8.2)
- **Minor:** 3 (F-2.2, F-3.5, F-4.3, F-9.3)

## Classification Breakdown

- **Code Bug:** 13 findings (F-3.2, F-3.3, F-3.5, F-4.2, F-5.2, F-5.3, F-5.4, F-6.1, F-6.2, F-6.3, F-6.4, F-6.5, F-9.1)
- **Architectural Flaw:** 12 findings (F-2.1, F-2.3, F-2.4, F-3.1, F-3.4, F-4.1, F-4.3, F-5.5, F-8.2, F-9.2, F-9.3)
- **Missing Feature:** 3 findings (F-4.4, F-7.1, F-7.2, F-7.3)
- **Economic Issue:** 2 findings (F-5.1, F-8.1)
- **Security Issue:** 1 finding (F-9.2 classified as potential)

## Critical Path Findings

These findings block production deployment per audit section 11:

1. **F-3.2** - Enrichment chain topology expansion dead code (empty entity list)
2. **F-6.2** - Embedding mask stored but never consumed by snap engine
3. **F-5.1** - LLM embedding cost unaddressed; economically non-viable at scale
4. **F-8.1** - No embedding caching, batching, or tiered enrichment strategy

## Systemic Patterns

1. **Integration gaps** - Subsystems built but not connected (Shadow Topology, embedding mask, telemetry alignment)
2. **Missing validation** - Weight profiles arbitrary; no A/B testing or empirical justification
3. **Economic model absent** - Design targets 10K events/min without cost ceiling or mitigation
4. **Operational observability gap** - Forensic capability exists; real-time health metrics do not
5. **Query performance** - N+1 patterns and unbounded data loading throughout
