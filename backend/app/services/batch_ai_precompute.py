"""
Batch AI pre-compute service — UI-view-aware top-N strategy.

After reconciliation completes, pre-computes LLM analysis for the TOP N
items (N=10) that will appear on the FIRST PAGE of each UI view the user
can select.  This ensures instant AI display for every filter/sort
combination without processing the entire divergence set.

UI view dimensions (from frontend divergence/page.tsx):
  Filters:  divergence_type  (6 values + unfiltered)
            domain           (dynamic + unfiltered)
  Sort:     confidence DESC  (default), confidence ASC,
            divergence_type DESC/ASC, domain DESC/ASC,
            target_type DESC/ASC, entity_name DESC/ASC

Strategy:
  1.  Discover which (divergence_type, domain) pairs actually exist.
  2.  For each UI "view" — a unique combination of (filter_type, filter_domain,
      sort_col, sort_dir) — run one SQL query that returns the top 10 result_ids.
  3.  Collect all unique result_ids across every view into a de-duplicated set.
  4.  Process ONLY those items through enrichment + LLM.

This keeps total LLM calls bounded:  even in the worst case the de-duped
set is far smaller than the full divergence count, and proportional to the
number of UI views rather than the dataset size.

Growing coverage (backfill):
  After the priority pass, a second "backfill" pass processes the NEXT
  BACKFILL_BUDGET items (confidence DESC) that still lack AI analysis.
  Each reconciliation run — or daily cron — adds another chunk, steadily
  growing coverage without overwhelming the LLM.  Over days the full
  dataset gets covered.

Gracefully degrades: if the LLM is unavailable or a single item fails,
the rest of the batch continues and divergences without AI analysis
fall back to rule-based enrichment only.
"""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.enrichment_llm import augment_enrichment

logger = logging.getLogger(__name__)

# Items per UI view to pre-compute (matches frontend page_size first page)
TOP_N = 10

# Additional items to backfill per run beyond the priority set.
# Keeps LLM load bounded: ~20 extra items * ~3 tok/s = ~10-15 min added.
BACKFILL_BUDGET = 20

# Seconds to pause between backfill LLM calls to limit CPU/memory pressure.
BACKFILL_THROTTLE_SECONDS = 2.0

# Sort columns the frontend can select (maps to SQL expressions)
SORT_COLUMNS = {
    "confidence":      "rr.confidence",
    "divergence_type": "rr.divergence_type",
    "domain":          "rr.domain",
    "target_type":     "rr.target_type",
    "entity_name":     "ne.name",
}

SORT_DIRS = ("DESC", "ASC")


async def precompute_ai_for_run(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Pre-compute AI analysis for UI-visible top-N items across all views.

    Returns summary: {"views_scanned": N, "unique_items": N,
                      "succeeded": N, "failed": N, "skipped": N}
    """
    # ------------------------------------------------------------------
    # Step 1: Discover which filter values actually exist in this run
    # ------------------------------------------------------------------
    type_rows = await db.execute(
        text(
            "SELECT DISTINCT divergence_type FROM reconciliation_results "
            "WHERE run_id = :rid AND tenant_id = :tid"
        ),
        {"rid": run_id, "tid": tenant_id},
    )
    existing_types = [r[0] for r in type_rows.fetchall()]

    domain_rows = await db.execute(
        text(
            "SELECT DISTINCT domain FROM reconciliation_results "
            "WHERE run_id = :rid AND tenant_id = :tid AND domain IS NOT NULL"
        ),
        {"rid": run_id, "tid": tenant_id},
    )
    existing_domains = [r[0] for r in domain_rows.fetchall()]

    # ------------------------------------------------------------------
    # Step 2: Enumerate UI views and collect top-N result_ids per view
    # ------------------------------------------------------------------
    target_ids: set[str] = set()
    views_scanned = 0

    # Build the list of filter combinations:
    #   (None, None)         = unfiltered
    #   (type, None)         = filtered by type only
    #   (None, domain)       = filtered by domain only
    #   (type, domain)       = filtered by both
    filter_combos: list[tuple[str | None, str | None]] = [(None, None)]
    for t in existing_types:
        filter_combos.append((t, None))
    for d in existing_domains:
        filter_combos.append((None, d))
    # type+domain combos — only those that actually have data
    for t in existing_types:
        for d in existing_domains:
            filter_combos.append((t, d))

    for ftype, fdomain in filter_combos:
        for sort_col_name, sort_col_sql in SORT_COLUMNS.items():
            for sort_dir in SORT_DIRS:
                ids = await _top_n_for_view(
                    db, tenant_id, run_id,
                    ftype, fdomain, sort_col_sql, sort_dir,
                )
                target_ids.update(ids)
                views_scanned += 1

    logger.info(
        "[BatchAI] Run %s: scanned %d views, %d unique items to process",
        run_id, views_scanned, len(target_ids),
    )

    # ------------------------------------------------------------------
    # Step 3: Fetch full records for de-duped items that need AI analysis
    # ------------------------------------------------------------------
    if not target_ids:
        return {"views_scanned": views_scanned, "unique_items": 0,
                "succeeded": 0, "failed": 0, "skipped": 0}

    # Filter to items that don't already have AI analysis
    placeholders = ", ".join(f":id{i}" for i in range(len(target_ids)))
    id_params = {f"id{i}": rid for i, rid in enumerate(target_ids)}

    rows = await db.execute(
        text(
            f"""
            SELECT rr.result_id, rr.divergence_type, rr.target_id, rr.target_type,
                   rr.domain, rr.description, rr.confidence, rr.extra,
                   rr.attribute_name, rr.cmdb_value, rr.observed_value,
                   ne.name AS entity_name, ne.external_id AS entity_external_id,
                   ne.entity_type AS cmdb_entity_type
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE rr.result_id IN ({placeholders})
              AND rr.tenant_id = :tid
              AND rr.ai_analysis IS NULL
            """  # nosec — placeholders are parameterised :id0, :id1, etc.
        ),
        {"tid": tenant_id, **id_params},
    )
    records = rows.mappings().fetchall()

    # ------------------------------------------------------------------
    # Step 4: Enrich + LLM for each item
    # ------------------------------------------------------------------
    succeeded = 0
    failed = 0
    skipped = 0
    total = len(records)

    logger.info(
        "[BatchAI] Processing %d items (of %d unique, some may already have AI)",
        total, len(target_ids),
    )

    for record in records:
        result_id = record["result_id"]
        div_type = record["divergence_type"]
        target_id = record["target_id"]

        try:
            enrichment = await _build_enrichment(
                db, metrics_db, tenant_id, div_type, target_id, record,
            )
            if not enrichment:
                skipped += 1
                continue

            ai_result = await augment_enrichment(enrichment, div_type, target_id)

            if ai_result:
                await db.execute(
                    text(
                        "UPDATE reconciliation_results "
                        "SET ai_analysis = CAST(:ai AS JSONB) "
                        "WHERE result_id = :rid"
                    ),
                    {"rid": result_id, "ai": json.dumps(ai_result)},
                )
                await db.commit()
                succeeded += 1
                if (succeeded % 5) == 0:
                    logger.info("[BatchAI] Progress: %d/%d succeeded", succeeded, total)
            else:
                failed += 1

        except Exception:
            logger.warning(
                "[BatchAI] Failed for %s (%s): %s",
                result_id, div_type, target_id, exc_info=True,
            )
            failed += 1
            await db.rollback()

    summary = {
        "views_scanned": views_scanned,
        "unique_items": len(target_ids),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info("[BatchAI] Run %s priority pass complete: %s", run_id, summary)
    return summary


# ---------------------------------------------------------------------------
# Backfill pass — grow coverage incrementally
# ---------------------------------------------------------------------------

async def backfill_ai_for_tenant(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    budget: int = BACKFILL_BUDGET,
    throttle: float = BACKFILL_THROTTLE_SECONDS,
) -> dict[str, Any]:
    """Process the next `budget` items lacking AI analysis, confidence DESC.

    Designed to be called:
      - Immediately after the priority pass (post-reconciliation).
      - On a daily cron to steadily grow coverage.

    Items already covered by the priority pass are skipped (ai_analysis IS NOT NULL).
    Each run picks up where the last left off.

    Returns summary: {"processed": N, "succeeded": N, "failed": N, "skipped": N,
                      "remaining": N}
    """
    # Count remaining items without AI analysis
    remaining_row = await db.execute(
        text(
            "SELECT COUNT(*) FROM reconciliation_results "
            "WHERE tenant_id = :tid AND ai_analysis IS NULL"
        ),
        {"tid": tenant_id},
    )
    remaining_before = remaining_row.scalar() or 0

    if remaining_before == 0:
        logger.info("[BatchAI-Backfill] Tenant %s: full coverage, nothing to do", tenant_id)
        return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0,
                "remaining": 0}

    # Fetch next chunk, highest confidence first
    rows = await db.execute(
        text(
            """
            SELECT rr.result_id, rr.divergence_type, rr.target_id, rr.target_type,
                   rr.domain, rr.description, rr.confidence, rr.extra,
                   rr.attribute_name, rr.cmdb_value, rr.observed_value,
                   ne.name AS entity_name, ne.external_id AS entity_external_id,
                   ne.entity_type AS cmdb_entity_type
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE rr.tenant_id = :tid
              AND rr.ai_analysis IS NULL
            ORDER BY rr.confidence DESC
            LIMIT :lim
            """
        ),
        {"tid": tenant_id, "lim": budget},
    )
    records = rows.mappings().fetchall()
    total = len(records)
    succeeded = 0
    failed = 0
    skipped = 0

    logger.info(
        "[BatchAI-Backfill] Tenant %s: processing %d items (%d remaining)",
        tenant_id, total, remaining_before,
    )

    for record in records:
        result_id = record["result_id"]
        div_type = record["divergence_type"]
        target_id = record["target_id"]

        try:
            enrichment = await _build_enrichment(
                db, metrics_db, tenant_id, div_type, target_id, record,
            )
            if not enrichment:
                skipped += 1
                continue

            ai_result = await augment_enrichment(enrichment, div_type, target_id)

            if ai_result:
                await db.execute(
                    text(
                        "UPDATE reconciliation_results "
                        "SET ai_analysis = CAST(:ai AS JSONB) "
                        "WHERE result_id = :rid"
                    ),
                    {"rid": result_id, "ai": json.dumps(ai_result)},
                )
                await db.commit()
                succeeded += 1
            else:
                failed += 1

        except Exception:
            logger.warning(
                "[BatchAI-Backfill] Failed for %s (%s): %s",
                result_id, div_type, target_id, exc_info=True,
            )
            failed += 1
            await db.rollback()

        # Throttle between items to limit CPU/memory pressure on ARM
        if throttle > 0:
            await asyncio.sleep(throttle)

    remaining_after = remaining_before - succeeded
    summary = {
        "processed": total,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "remaining": max(remaining_after, 0),
    }
    logger.info("[BatchAI-Backfill] Tenant %s complete: %s", tenant_id, summary)
    return summary


# ---------------------------------------------------------------------------
# Top-N query per UI view
# ---------------------------------------------------------------------------

async def _top_n_for_view(
    db: AsyncSession,
    tenant_id: str,
    run_id: str,
    filter_type: str | None,
    filter_domain: str | None,
    sort_col_sql: str,
    sort_dir: str,
) -> list[str]:
    """Return up to TOP_N result_ids for a specific UI filter+sort view."""
    where_clauses = ["rr.tenant_id = :tid", "rr.run_id = :rid"]
    params: dict[str, Any] = {"tid": tenant_id, "rid": run_id, "lim": TOP_N}

    if filter_type:
        where_clauses.append("rr.divergence_type = :ftype")
        params["ftype"] = filter_type
    if filter_domain:
        where_clauses.append("rr.domain = :fdomain")
        params["fdomain"] = filter_domain

    where = " AND ".join(where_clauses)

    # NULLS LAST keeps sort consistent with the frontend's experience
    rows = await db.execute(
        text(
            f"""
            SELECT rr.result_id
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE {where}
            ORDER BY {sort_col_sql} {sort_dir} NULLS LAST
            LIMIT :lim
            """  # nosec — sort_col_sql from SORT_COLUMNS whitelist
        ),
        params,
    )
    return [r[0] for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# Enrichment builders per divergence type
# ---------------------------------------------------------------------------

async def _build_enrichment(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    div_type: str,
    target_id: str,
    record: Any,
) -> dict | None:
    """Build the enrichment dict that the LLM prompt builder expects."""
    builder = _ENRICHMENT_BUILDERS.get(div_type)
    if not builder:
        return _build_generic_enrichment(record)
    return await builder(db, metrics_db, tenant_id, target_id, record)


async def _build_dark_node_enrichment(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    target_id: str,
    record: Any,
) -> dict:
    """Build dark_node enrichment from KPI metadata, alarms, neighbours."""
    # KPI metadata
    kpi_meta = await metrics_db.execute(
        text(
            """
            SELECT
                metadata->>'domain' AS domain,
                metadata->>'vendor' AS vendor,
                metadata->>'rat_type' AS rat_type,
                metadata->>'band' AS band,
                COUNT(*) AS sample_count,
                COUNT(DISTINCT kpi_name) AS distinct_kpis,
                MIN(timestamp) AS first_seen,
                MAX(timestamp) AS last_seen
            FROM kpi_metrics
            WHERE tenant_id = :tid AND entity_id = :eid
            GROUP BY metadata->>'domain', metadata->>'vendor',
                     metadata->>'rat_type', metadata->>'band'
            ORDER BY sample_count DESC
            LIMIT 3
            """
        ),
        {"tid": tenant_id, "eid": target_id},
    )
    profiles = kpi_meta.fetchall()
    primary = profiles[0] if profiles else None

    # KPI names
    kpi_names_row = await metrics_db.execute(
        text(
            "SELECT DISTINCT kpi_name FROM kpi_metrics "
            "WHERE tenant_id = :tid AND entity_id = :eid "
            "ORDER BY kpi_name LIMIT 30"
        ),
        {"tid": tenant_id, "eid": target_id},
    )
    kpi_names = [r[0] for r in kpi_names_row.fetchall()]

    # Alarm profile
    alarm_row = await db.execute(
        text(
            """
            SELECT alarm_type, severity, COUNT(*) AS cnt
            FROM telco_events_alarms
            WHERE tenant_id = :tid AND entity_id = :eid
            GROUP BY alarm_type, severity
            ORDER BY cnt DESC
            LIMIT 5
            """
        ),
        {"tid": tenant_id, "eid": target_id},
    )
    alarm_profiles = [
        {"alarm_type": r[0], "severity": r[1], "count": r[2]}
        for r in alarm_row.fetchall()
    ]

    # Neighbour count
    nr_count = await db.execute(
        text(
            "SELECT COUNT(*) FROM neighbour_relations "
            "WHERE tenant_id = :tid AND (from_cell_id = :eid OR to_cell_id = :eid)"
        ),
        {"tid": tenant_id, "eid": target_id},
    )
    neighbour_count = nr_count.scalar() or 0

    # Infer device type
    inferred_type = "UNKNOWN"
    type_confidence = 0.0
    if primary:
        rat = (primary[2] or "").upper()
        if "NR" in rat or "5G" in rat:
            inferred_type, type_confidence = "NR_CELL", 0.85
        elif "LTE" in rat or "4G" in rat:
            inferred_type, type_confidence = "LTE_CELL", 0.85

    # Infer role
    role = "Network Element"
    ran_kpis = [k for k in kpi_names if any(
        x in k.lower() for x in ["throughput", "prb", "rsrp", "sinr", "handover"]
    )]
    if ran_kpis:
        role = "RAN Access Point"

    return {
        "inferred_device_type": inferred_type,
        "device_type_confidence": type_confidence,
        "inferred_role": role,
        "domain": primary[0] if primary else record.get("domain"),
        "rat_type": primary[2] if primary else None,
        "vendor_hint": primary[1] if primary else None,
        "observation_window": {
            "first_seen": str(primary[6]) if primary and primary[6] else None,
            "last_seen": str(primary[7]) if primary and primary[7] else None,
            "total_samples": sum(p[4] for p in profiles) if profiles else 0,
            "distinct_kpis": len(kpi_names),
        },
        "kpi_names": kpi_names[:15],
        "alarm_profiles": alarm_profiles,
        "topology_context": {"neighbour_count": neighbour_count},
        "confidence": float(record["confidence"]),
    }


async def _build_phantom_node_enrichment(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    target_id: str,
    record: Any,
) -> dict:
    return {
        "entity_type": record.get("cmdb_entity_type") or record.get("target_type"),
        "entity_name": record.get("entity_name"),
        "detection_method": "signal_absence",
        "signals_checked": ["kpi_metrics", "telco_events_alarms", "neighbour_relations"],
        "confidence": float(record["confidence"]),
    }


async def _build_dark_edge_enrichment(
    db: AsyncSession,
    metrics_db: AsyncSession,
    tenant_id: str,
    target_id: str,
    record: Any,
) -> dict:
    nr = await db.execute(
        text(
            """
            SELECT nr.from_cell_id, nr.to_cell_id, nr.neighbour_type,
                   nr.handover_attempts, nr.handover_success_rate, nr.distance_m,
                   ne_from.name AS from_name, ne_to.name AS to_name
            FROM neighbour_relations nr
            LEFT JOIN network_entities ne_from
              ON CAST(ne_from.id AS TEXT) = nr.from_cell_id AND ne_from.tenant_id = :tid
            LEFT JOIN network_entities ne_to
              ON CAST(ne_to.id AS TEXT) = nr.to_cell_id AND ne_to.tenant_id = :tid
            WHERE nr.relation_id = :rid AND nr.tenant_id = :tid
            """
        ),
        {"rid": target_id, "tid": tenant_id},
    )
    nr_rec = nr.mappings().fetchone()

    return {
        "neighbour_relation": {
            "from_name": (nr_rec["from_name"] if nr_rec else None) or target_id,
            "to_name": (nr_rec["to_name"] if nr_rec else None) or "unknown",
            "neighbour_type": nr_rec["neighbour_type"] if nr_rec else None,
            "handover_attempts": nr_rec["handover_attempts"] if nr_rec else None,
            "handover_success_rate": float(nr_rec["handover_success_rate"]) if nr_rec and nr_rec.get("handover_success_rate") else None,
            "distance_m": float(nr_rec["distance_m"]) if nr_rec and nr_rec.get("distance_m") else None,
        },
        "confidence": float(record["confidence"]),
    }


def _build_generic_enrichment(record: Any) -> dict:
    """Build enrichment for types without a specific builder."""
    reasoning = []
    if record.get("description"):
        reasoning.append(record["description"])
    if record.get("attribute_name"):
        reasoning.append(
            f"CMDB declares {record['attribute_name']} = '{record.get('cmdb_value')}', "
            f"observed = '{record.get('observed_value')}'"
        )

    return {
        "reasoning": reasoning,
        "remediation_options": [],
        "confidence": float(record["confidence"]),
    }


_ENRICHMENT_BUILDERS = {
    "dark_node": _build_dark_node_enrichment,
    "phantom_node": _build_phantom_node_enrichment,
    "dark_edge": _build_dark_edge_enrichment,
}
