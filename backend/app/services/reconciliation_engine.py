"""
ReconciliationEngine — Signal-based divergence detection service.

Detects CMDB inconsistencies by cross-referencing the declared topology
(network_entities, topology_relationships) against operational signals:

  - KPI telemetry   (kpi_metrics)
  - Alarms/events   (telco_events_alarms)
  - Neighbour rels   (neighbour_relations)

NO ground-truth tables are accessed. Detection is pure inference:

  - Dark Nodes         : Entity seen in telemetry/alarms but absent from CMDB
  - Phantom Nodes      : CMDB entity with zero operational footprint
  - Identity Mutations : Hardware fingerprint swap, site-ID drift, or ID collision
  - Dark Attributes    : KPI metadata contradicts CMDB-declared attributes
  - Dark Edges         : Neighbour relation exists but no CMDB topology edge
  - Phantom Edges      : CMDB topology edge where neither endpoint shows activity

Ground-truth tables (gt_network_entities, gt_entity_relationships,
divergence_manifest) are NEVER referenced here. Scoring against ground
truth is handled exclusively by the separate DivergenceScorer module.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# KPI metadata attributes that can be cross-checked against CMDB attributes.
# When kpi_metrics.metadata reports a different value than network_entities.attributes,
# that signals a stale or incorrect CMDB record.
CROSSCHECK_ATTRIBUTES = [
    "vendor",
    "band",
    "rat_type",
]

# Batch size for bulk inserts
BATCH_SIZE = 2000


def _make_result_id(*parts: str) -> str:
    """Deterministic ID from components — idempotent across runs."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Tables that the operational engine must NEVER query.
# ---------------------------------------------------------------------------
EVALUATION_TABLES = frozenset({
    "gt_network_entities",
    "gt_entity_relationships",
    "divergence_manifest",
})


class ReconciliationEngine:
    """
    Infers CMDB divergences from operational signals only.

    Data sources used (all operational):
      - network_entities          (CMDB declared entities)
      - topology_relationships    (CMDB declared edges)
      - kpi_metrics               (telemetry time-series)
      - telco_events_alarms       (alarm/event feed)
      - neighbour_relations       (cell-to-cell neighbour data)

    Data sources NEVER used:
      - gt_network_entities       (evaluation only)
      - gt_entity_relationships   (evaluation only)
      - divergence_manifest       (evaluation only)

    Usage:
        engine = ReconciliationEngine(db_session)
        summary = await engine.run(tenant_id="pedkai_telco2_01")
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.run_id: str = ""
        self.tenant_id: str = ""

    async def run(self, tenant_id: str) -> dict[str, Any]:
        """Execute full signal-based divergence detection."""
        self.tenant_id = tenant_id
        self.run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        logger.info(
            f"[Reconciliation] Starting signal-based run {self.run_id} "
            f"for tenant {tenant_id}"
        )

        try:
            await self._ensure_tables()
            await self._clear_previous_run(tenant_id)

            # --- Operational inventory ---
            cmdb_entity_count = await self._scalar(
                "SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            cmdb_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )

            # Count distinct entities seen in operational signals
            observed_entity_count = await self._scalar(
                """
                SELECT COUNT(DISTINCT entity_id) FROM (
                    SELECT entity_id FROM kpi_metrics WHERE tenant_id = :tid
                    UNION
                    SELECT entity_id FROM telco_events_alarms WHERE tenant_id = :tid
                ) observed
                """,
                {"tid": tenant_id},
            )

            # Count distinct neighbour-relation edges
            observed_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM neighbour_relations WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )

            # --- Detection ---
            counts: dict[str, int] = {}
            counts["dark_nodes"] = await self._detect_dark_nodes()
            counts["phantom_nodes"] = await self._detect_phantom_nodes()
            counts["identity_mutations"] = await self._detect_identity_mutations()
            counts["dark_attributes"] = await self._detect_dark_attributes()
            counts["dark_edges"] = await self._detect_dark_edges()
            counts["phantom_edges"] = await self._detect_phantom_edges()

            total = sum(counts.values())

            completed_at = datetime.now(timezone.utc)
            duration_s = (completed_at - started_at).total_seconds()

            # --- Persist run metadata ---
            await self.session.execute(
                text(
                    """
                    INSERT INTO reconciliation_runs (
                        run_id, tenant_id, triggered_by, status,
                        total_divergences, dark_nodes, phantom_nodes,
                        identity_mutations, dark_attributes, dark_edges, phantom_edges,
                        cmdb_entity_count, observed_entity_count,
                        cmdb_edge_count, observed_edge_count,
                        started_at, completed_at
                    ) VALUES (
                        :run_id, :tid, 'manual', 'complete',
                        :total, :dark_nodes, :phantom_nodes,
                        :identity_mutations, :dark_attributes, :dark_edges, :phantom_edges,
                        :cmdb_entities, :obs_entities,
                        :cmdb_edges, :obs_edges,
                        :started_at, :completed_at
                    )
                    ON CONFLICT (run_id) DO NOTHING
                    """
                ),
                {
                    "run_id": self.run_id,
                    "tid": tenant_id,
                    "total": str(total),
                    "dark_nodes": str(counts["dark_nodes"]),
                    "phantom_nodes": str(counts["phantom_nodes"]),
                    "identity_mutations": str(counts["identity_mutations"]),
                    "dark_attributes": str(counts["dark_attributes"]),
                    "dark_edges": str(counts["dark_edges"]),
                    "phantom_edges": str(counts["phantom_edges"]),
                    "cmdb_entities": str(cmdb_entity_count),
                    "obs_entities": str(observed_entity_count),
                    "cmdb_edges": str(cmdb_edge_count),
                    "obs_edges": str(observed_edge_count),
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
            await self.session.commit()

            logger.info(
                f"[Reconciliation] Run {self.run_id} complete: "
                f"{total:,} divergences in {duration_s:.1f}s"
            )

            return {
                "run_id": self.run_id,
                "tenant_id": tenant_id,
                "status": "complete",
                "duration_seconds": round(duration_s, 1),
                "divergences": {
                    "total": total,
                    **counts,
                },
                "operational_inventory": {
                    "cmdb_entity_count": cmdb_entity_count,
                    "observed_entity_count": observed_entity_count,
                    "cmdb_edge_count": cmdb_edge_count,
                    "observed_edge_count": observed_edge_count,
                },
            }

        except Exception as exc:
            logger.error(
                f"[Reconciliation] Run {self.run_id} failed: {exc}",
                exc_info=True,
            )
            await self.session.rollback()
            raise

    # ------------------------------------------------------------------
    # Detection methods — ALL use operational signals only
    # ------------------------------------------------------------------

    async def _detect_dark_nodes(self) -> int:
        """
        Dark nodes: entities observed in telemetry or alarms but absent
        from the CMDB.  These are real network elements carrying traffic
        that the CMDB does not know about.

        Signal sources: kpi_metrics, telco_events_alarms
        CMDB reference: network_entities
        """
        logger.info("[Reconciliation] Detecting dark nodes from operational signals...")
        rows = await self._fetch(
            """
            SELECT
                obs.entity_id  AS target_id,
                obs.sources    AS sources,
                obs.domain     AS domain
            FROM (
                SELECT
                    km.entity_id,
                    'kpi_telemetry' AS sources,
                    km.metadata->>'domain' AS domain
                FROM kpi_metrics km
                WHERE km.tenant_id = :tid
                GROUP BY km.entity_id, km.metadata->>'domain'

                UNION

                SELECT
                    a.entity_id,
                    'alarm_feed' AS sources,
                    a.domain
                FROM telco_events_alarms a
                WHERE a.tenant_id = :tid
                GROUP BY a.entity_id, a.domain
            ) obs
            WHERE NOT EXISTS (
                SELECT 1 FROM network_entities ne
                WHERE (CAST(ne.id AS TEXT) = obs.entity_id
                       OR ne.external_id = obs.entity_id)
                  AND ne.tenant_id = :tid
            )
            """,
            {"tid": self.tenant_id},
        )

        # Deduplicate by entity_id (may appear in both KPI and alarm sources)
        seen: dict[str, dict] = {}
        for r in rows:
            eid = r["target_id"]
            if eid not in seen:
                seen[eid] = r
            else:
                existing_src = seen[eid]["sources"]
                if r["sources"] not in existing_src:
                    seen[eid]["sources"] = f"{existing_src}, {r['sources']}"

        records = [
            {
                "result_id": _make_result_id(self.tenant_id, "dark_node", eid),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "dark_node",
                "entity_or_relationship": "entity",
                "target_id": eid,
                "target_type": "UNKNOWN",
                "domain": r["domain"],
                "description": (
                    f"Entity '{eid}' observed in operational signals "
                    f"({r['sources']}) but absent from CMDB. "
                    f"Likely an unregistered network element."
                ),
                "confidence": 0.85,
            }
            for eid, r in seen.items()
        ]
        await self._bulk_insert(records)
        logger.info(f"  -> {len(records):,} dark nodes")
        return len(records)

    async def _detect_phantom_nodes(self) -> int:
        """
        Phantom nodes: CMDB entities with zero operational footprint.
        No KPI telemetry, no alarms, no neighbour relations reference them.

        Signal sources: kpi_metrics, telco_events_alarms, neighbour_relations
        CMDB reference: network_entities
        """
        logger.info("[Reconciliation] Detecting phantom nodes from signal absence...")
        rows = await self._fetch(
            """
            SELECT
                CAST(ne.id AS TEXT)          AS target_id,
                ne.entity_type               AS target_type,
                ne.name                      AS name,
                ne.attributes->>'domain'     AS domain
            FROM network_entities ne
            WHERE ne.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM kpi_metrics km
                  WHERE km.tenant_id = :tid
                    AND (km.entity_id = CAST(ne.id AS TEXT)
                         OR km.entity_id = ne.external_id)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM telco_events_alarms a
                  WHERE a.tenant_id = :tid
                    AND (a.entity_id = CAST(ne.id AS TEXT)
                         OR a.entity_id = ne.external_id)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM neighbour_relations nr
                  WHERE nr.tenant_id = :tid
                    AND (nr.from_cell_id = CAST(ne.id AS TEXT)
                         OR nr.to_cell_id = CAST(ne.id AS TEXT)
                         OR nr.from_cell_id = ne.external_id
                         OR nr.to_cell_id = ne.external_id)
              )
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(self.tenant_id, "phantom_node", r["target_id"]),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "phantom_node",
                "entity_or_relationship": "entity",
                "target_id": r["target_id"],
                "target_type": r["target_type"],
                "domain": r["domain"],
                "description": (
                    f"CMDB entity {r['name']} ({r['target_type']}) has no operational "
                    f"footprint — zero KPI samples, zero alarms, zero neighbour "
                    f"relations. May be decommissioned or a phantom CI."
                ),
                "confidence": 0.75,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  -> {len(records):,} phantom nodes")
        return len(records)

    async def _detect_identity_mutations(self) -> int:
        """
        Identity mutations: evidence that the physical equipment behind a
        CMDB record has changed (hardware swap, reidentification, ID collision)
        without the CMDB being updated.

        Three independent detection strategies, all signal-based:

        1. Hardware fingerprint swap — KPI telemetry consistently reports a
           different (vendor, rat_type) pair than the CMDB. A single-attribute
           mismatch is a dark_attribute; a multi-attribute fingerprint change
           is stronger evidence of wholesale hardware replacement.

        2. Site-ID drift — KPI metadata reports site_id X for an entity, but
           the CMDB declares the entity belongs to site_id Y. Implies the
           entity was moved or re-homed without CMDB update.

        3. Multi-entity ID collision — Two or more CMDB entities with different
           UUIDs both have external_ids that map to the same KPI telemetry
           entity_id. At most one can be correct; the rest have stale IDs.

        Signal sources: kpi_metrics, network_entities
        """
        logger.info("[Reconciliation] Detecting identity mutations from operational signals...")
        all_records: list[dict] = []

        # --- Strategy 1: Hardware fingerprint swap ---
        # If BOTH vendor AND rat_type in telemetry differ from CMDB,
        # that's strong evidence of a hardware swap, not just a data-entry error.
        hw_rows = await self._fetch(
            """
            WITH telemetry_fingerprint AS (
                SELECT
                    km.entity_id,
                    km.metadata->>'vendor'   AS tel_vendor,
                    km.metadata->>'rat_type' AS tel_rat,
                    COUNT(*) AS sample_count
                FROM kpi_metrics km
                WHERE km.tenant_id = :tid
                  AND km.metadata->>'vendor' IS NOT NULL
                  AND km.metadata->>'rat_type' IS NOT NULL
                GROUP BY km.entity_id, km.metadata->>'vendor', km.metadata->>'rat_type'
            ),
            -- Pick the dominant fingerprint per entity (mode)
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY entity_id ORDER BY sample_count DESC
                    ) AS rn
                FROM telemetry_fingerprint
            )
            SELECT
                CAST(ne.id AS TEXT)       AS target_id,
                ne.entity_type            AS target_type,
                ne.name                   AS name,
                ne.attributes->>'domain'  AS domain,
                ne.attributes->>'vendor'  AS cmdb_vendor,
                ne.attributes->>'rat_type' AS cmdb_rat,
                r.tel_vendor              AS observed_vendor,
                r.tel_rat                 AS observed_rat,
                r.sample_count
            FROM ranked r
            JOIN network_entities ne ON (
                CAST(ne.id AS TEXT) = r.entity_id
                OR ne.external_id = r.entity_id
            )
            WHERE r.rn = 1
              AND ne.tenant_id = :tid
              AND ne.attributes->>'vendor' IS NOT NULL
              AND ne.attributes->>'rat_type' IS NOT NULL
              -- Both must differ (single-attr mismatches are dark_attribute)
              AND LOWER(TRIM(ne.attributes->>'vendor')) != LOWER(TRIM(r.tel_vendor))
              AND LOWER(TRIM(ne.attributes->>'rat_type')) != LOWER(TRIM(r.tel_rat))
            """,
            {"tid": self.tenant_id},
        )
        for r in hw_rows:
            cmdb_fp = f"{r['cmdb_vendor']}/{r['cmdb_rat']}"
            obs_fp = f"{r['observed_vendor']}/{r['observed_rat']}"
            all_records.append(
                {
                    "result_id": _make_result_id(
                        self.tenant_id, "identity_mutation", "hw_swap", r["target_id"]
                    ),
                    "tenant_id": self.tenant_id,
                    "run_id": self.run_id,
                    "divergence_type": "identity_mutation",
                    "entity_or_relationship": "entity",
                    "target_id": r["target_id"],
                    "target_type": r["target_type"],
                    "domain": r["domain"],
                    "description": (
                        f"Hardware fingerprint swap: {r['name']} ({r['target_type']}) "
                        f"CMDB declares {cmdb_fp} but telemetry reports {obs_fp} "
                        f"({r['sample_count']} samples). Likely hardware replacement "
                        f"without CMDB update."
                    ),
                    "attribute_name": "vendor+rat_type",
                    "cmdb_value": cmdb_fp,
                    "observed_value": obs_fp,
                    "confidence": min(0.95, 0.6 + 0.04 * min(r["sample_count"], 9)),
                }
            )

        # --- Strategy 2: Site-ID drift ---
        # KPI metadata reports a site_id that differs from CMDB's site_id
        # for the same entity. The entity was moved or re-homed.
        site_rows = await self._fetch(
            """
            WITH tel_site AS (
                SELECT
                    km.entity_id,
                    km.metadata->>'site_id' AS tel_site_id,
                    COUNT(*) AS sample_count
                FROM kpi_metrics km
                WHERE km.tenant_id = :tid
                  AND km.metadata->>'site_id' IS NOT NULL
                GROUP BY km.entity_id, km.metadata->>'site_id'
            ),
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY entity_id ORDER BY sample_count DESC
                    ) AS rn
                FROM tel_site
            )
            SELECT
                CAST(ne.id AS TEXT)             AS target_id,
                ne.entity_type                  AS target_type,
                ne.name                         AS name,
                ne.attributes->>'domain'        AS domain,
                ne.attributes->>'site_id'       AS cmdb_site_id,
                r.tel_site_id                   AS observed_site_id,
                r.sample_count
            FROM ranked r
            JOIN network_entities ne ON (
                CAST(ne.id AS TEXT) = r.entity_id
                OR ne.external_id = r.entity_id
            )
            WHERE r.rn = 1
              AND ne.tenant_id = :tid
              AND ne.attributes->>'site_id' IS NOT NULL
              AND r.tel_site_id IS NOT NULL
              AND ne.attributes->>'site_id' != r.tel_site_id
            """,
            {"tid": self.tenant_id},
        )
        for r in site_rows:
            # Skip if this entity already flagged as hw_swap (avoid duplicates)
            rid = _make_result_id(
                self.tenant_id, "identity_mutation", "site_drift", r["target_id"]
            )
            all_records.append(
                {
                    "result_id": rid,
                    "tenant_id": self.tenant_id,
                    "run_id": self.run_id,
                    "divergence_type": "identity_mutation",
                    "entity_or_relationship": "entity",
                    "target_id": r["target_id"],
                    "target_type": r["target_type"],
                    "domain": r["domain"],
                    "description": (
                        f"Site-ID drift: {r['name']} ({r['target_type']}) "
                        f"CMDB says site '{r['cmdb_site_id']}' but telemetry "
                        f"reports site '{r['observed_site_id']}' "
                        f"({r['sample_count']} samples). Entity may have been "
                        f"physically relocated or re-homed without CMDB update."
                    ),
                    "attribute_name": "site_id",
                    "cmdb_value": r["cmdb_site_id"],
                    "observed_value": r["observed_site_id"],
                    "confidence": min(0.90, 0.5 + 0.05 * min(r["sample_count"], 8)),
                }
            )

        # --- Strategy 3: Multi-entity ID collision ---
        # Two or more CMDB entities (different UUIDs) whose external_ids
        # both receive the same KPI telemetry entity_id. This means the
        # external_id was reused or one entity was replaced and the old
        # CMDB record was not removed.
        collision_rows = await self._fetch(
            """
            WITH kpi_entity_ids AS (
                SELECT DISTINCT entity_id
                FROM kpi_metrics
                WHERE tenant_id = :tid
            ),
            cmdb_matches AS (
                SELECT
                    k.entity_id AS kpi_eid,
                    CAST(ne.id AS TEXT) AS cmdb_uuid,
                    ne.external_id,
                    ne.name,
                    ne.entity_type,
                    ne.attributes->>'domain' AS domain
                FROM kpi_entity_ids k
                JOIN network_entities ne ON (
                    ne.external_id = k.entity_id
                    AND ne.tenant_id = :tid
                )
            ),
            -- Find kpi entity_ids that match multiple CMDB entities
            collisions AS (
                SELECT kpi_eid, COUNT(*) AS match_count
                FROM cmdb_matches
                GROUP BY kpi_eid
                HAVING COUNT(*) > 1
            )
            SELECT
                cm.kpi_eid,
                cm.cmdb_uuid,
                cm.external_id,
                cm.name,
                cm.entity_type,
                cm.domain,
                c.match_count
            FROM collisions c
            JOIN cmdb_matches cm ON cm.kpi_eid = c.kpi_eid
            ORDER BY c.kpi_eid, cm.cmdb_uuid
            """,
            {"tid": self.tenant_id},
        )

        # Group collision rows by kpi_eid to build descriptions
        collision_groups: dict[str, list[dict]] = {}
        for r in collision_rows:
            collision_groups.setdefault(r["kpi_eid"], []).append(r)

        for kpi_eid, group in collision_groups.items():
            names = ", ".join(f"{g['name']} ({g['cmdb_uuid'][:8]})" for g in group)
            for g in group:
                all_records.append(
                    {
                        "result_id": _make_result_id(
                            self.tenant_id, "identity_mutation", "id_collision",
                            g["cmdb_uuid"]
                        ),
                        "tenant_id": self.tenant_id,
                        "run_id": self.run_id,
                        "divergence_type": "identity_mutation",
                        "entity_or_relationship": "entity",
                        "target_id": g["cmdb_uuid"],
                        "target_type": g["entity_type"],
                        "domain": g["domain"],
                        "description": (
                            f"ID collision: {len(group)} CMDB entities share "
                            f"external_id '{kpi_eid}' in telemetry: {names}. "
                            f"At most one is correct; the others have stale "
                            f"identifiers from hardware replacement or "
                            f"CMDB copy-paste errors."
                        ),
                        "attribute_name": "external_id",
                        "cmdb_value": g["external_id"],
                        "observed_value": f"collision:{kpi_eid}",
                        "confidence": 0.90,
                    }
                )

        await self._bulk_insert(all_records)
        logger.info(f"  -> {len(all_records):,} identity mutations")
        return len(all_records)

    async def _detect_dark_attributes(self) -> int:
        """
        Dark attributes: CMDB entity attributes that conflict with values
        reported in KPI telemetry metadata.

        Signal source: kpi_metrics.metadata
        CMDB reference: network_entities.attributes
        """
        logger.info("[Reconciliation] Detecting dark attributes from KPI metadata...")
        all_records: list[dict] = []

        for attr in CROSSCHECK_ATTRIBUTES:
            rows = await self._fetch(
                f"""
                SELECT
                    CAST(ne.id AS TEXT)           AS target_id,
                    ne.entity_type                AS target_type,
                    ne.name                       AS name,
                    ne.attributes->>'domain'      AS domain,
                    ne.attributes->>'{attr}'      AS cmdb_val,
                    km_agg.observed_val           AS observed_val,
                    km_agg.sample_count           AS sample_count
                FROM network_entities ne
                JOIN (
                    SELECT
                        km.entity_id,
                        km.metadata->>'{attr}'  AS observed_val,
                        COUNT(*)                AS sample_count
                    FROM kpi_metrics km
                    WHERE km.tenant_id = :tid
                      AND km.metadata->>'{attr}' IS NOT NULL
                    GROUP BY km.entity_id, km.metadata->>'{attr}'
                ) km_agg ON (
                    km_agg.entity_id = CAST(ne.id AS TEXT)
                    OR km_agg.entity_id = ne.external_id
                )
                WHERE ne.tenant_id = :tid
                  AND ne.attributes->>'{attr}' IS NOT NULL
                  AND km_agg.observed_val IS NOT NULL
                  AND LOWER(TRIM(ne.attributes->>'{attr}'))
                      != LOWER(TRIM(km_agg.observed_val))
                """,  # nosec — attr from hardcoded CROSSCHECK_ATTRIBUTES list
                {"tid": self.tenant_id},
            )

            # For each entity, keep only the observation with highest sample_count
            best_per_entity: dict[str, dict] = {}
            for r in rows:
                eid = r["target_id"]
                if eid not in best_per_entity or r["sample_count"] > best_per_entity[eid]["sample_count"]:
                    best_per_entity[eid] = r

            for r in best_per_entity.values():
                all_records.append(
                    {
                        "result_id": _make_result_id(
                            self.tenant_id, "dark_attribute", r["target_id"], attr
                        ),
                        "tenant_id": self.tenant_id,
                        "run_id": self.run_id,
                        "divergence_type": "dark_attribute",
                        "entity_or_relationship": "entity",
                        "target_id": r["target_id"],
                        "target_type": r["target_type"],
                        "domain": r["domain"],
                        "description": (
                            f"Attribute '{attr}' conflict: CMDB declares "
                            f"'{r['cmdb_val']}' but telemetry reports "
                            f"'{r['observed_val']}' ({r['sample_count']} samples). "
                            f"Entity: {r['name']} ({r['target_type']})."
                        ),
                        "attribute_name": attr,
                        "cmdb_value": r["cmdb_val"],
                        "observed_value": r["observed_val"],
                        "confidence": min(0.95, 0.5 + 0.05 * min(r["sample_count"], 9)),
                    }
                )

        await self._bulk_insert(all_records)
        logger.info(f"  -> {len(all_records):,} dark attributes")
        return len(all_records)

    async def _detect_dark_edges(self) -> int:
        """
        Dark edges: neighbour relations that exist in operational data
        but have no corresponding CMDB topology edge.

        Signal source: neighbour_relations
        CMDB reference: topology_relationships
        """
        logger.info("[Reconciliation] Detecting dark edges from neighbour relations...")
        rows = await self._fetch(
            """
            SELECT
                nr.relation_id          AS target_id,
                nr.from_cell_id         AS from_id,
                nr.to_cell_id           AS to_id,
                nr.neighbour_type       AS rel_type,
                nr.handover_attempts    AS ho_attempts,
                nr.handover_success_rate AS ho_rate
            FROM neighbour_relations nr
            WHERE nr.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM topology_relationships tr
                  WHERE tr.tenant_id = :tid
                    AND (
                        (tr.from_entity_id = nr.from_cell_id
                         AND tr.to_entity_id = nr.to_cell_id)
                        OR
                        (tr.from_entity_id = nr.to_cell_id
                         AND tr.to_entity_id = nr.from_cell_id)
                    )
              )
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(
                    self.tenant_id, "dark_edge",
                    r["from_id"], r["to_id"], r["rel_type"] or "neighbour"
                ),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "dark_edge",
                "entity_or_relationship": "relationship",
                "target_id": r["target_id"],
                "target_type": r["rel_type"] or "neighbour",
                "domain": "mobile_ran",
                "description": (
                    f"Neighbour relation {r['from_id']} -> {r['to_id']} "
                    f"({r['rel_type'] or 'neighbour'}) observed in operational data "
                    f"but not declared in CMDB topology. "
                    f"HO attempts: {r['ho_attempts']}, success rate: {r['ho_rate']}."
                ),
                "confidence": 0.80,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  -> {len(records):,} dark edges")
        return len(records)

    async def _detect_phantom_edges(self) -> int:
        """
        Phantom edges: CMDB topology edges where neither endpoint shows
        any operational activity (KPI or alarm).

        Signal sources: kpi_metrics, telco_events_alarms
        CMDB reference: topology_relationships
        """
        logger.info("[Reconciliation] Detecting phantom edges from signal absence...")
        rows = await self._fetch(
            """
            SELECT
                CAST(tr.id AS TEXT)  AS target_id,
                tr.relationship_type AS rel_type,
                tr.from_entity_id    AS from_id,
                tr.from_entity_type  AS from_type,
                tr.to_entity_id      AS to_id,
                tr.to_entity_type    AS to_type
            FROM topology_relationships tr
            WHERE tr.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM kpi_metrics km
                  WHERE km.tenant_id = :tid
                    AND km.entity_id IN (tr.from_entity_id, tr.to_entity_id)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM telco_events_alarms a
                  WHERE a.tenant_id = :tid
                    AND a.entity_id IN (tr.from_entity_id, tr.to_entity_id)
              )
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(
                    self.tenant_id, "phantom_edge",
                    r["from_id"], r["to_id"], r["rel_type"]
                ),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "phantom_edge",
                "entity_or_relationship": "relationship",
                "target_id": r["target_id"],
                "target_type": r["rel_type"],
                "domain": None,
                "description": (
                    f"Stale CMDB edge: {r['from_type']} ({r['from_id']}) -> "
                    f"{r['to_type']} ({r['to_id']}) ({r['rel_type']}) — "
                    f"neither endpoint has KPI or alarm activity."
                ),
                "confidence": 0.70,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  -> {len(records):,} phantom edges")
        return len(records)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def _fetch(self, sql: str, params: dict) -> list[dict]:
        result = await self.session.execute(text(sql), params)
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]

    async def _scalar(self, sql: str, params: dict) -> int:
        result = await self.session.execute(text(sql), params)
        val = result.scalar()
        return int(val) if val is not None else 0

    async def _bulk_insert(self, records: list[dict]) -> None:
        if not records:
            return
        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            await self.session.execute(
                text(
                    """
                    INSERT INTO reconciliation_results (
                        result_id, tenant_id, run_id, divergence_type,
                        entity_or_relationship, target_id, target_type, domain,
                        description, attribute_name, cmdb_value, observed_value,
                        confidence
                    ) VALUES (
                        :result_id, :tenant_id, :run_id, :divergence_type,
                        :entity_or_relationship, :target_id, :target_type, :domain,
                        :description, :attribute_name, :cmdb_value, :observed_value,
                        :confidence
                    )
                    ON CONFLICT (result_id) DO NOTHING
                    """
                ),
                [
                    {
                        "attribute_name": r.get("attribute_name"),
                        "cmdb_value": r.get("cmdb_value"),
                        "observed_value": r.get("observed_value"),
                        **r,
                    }
                    for r in chunk
                ],
            )
            await self.session.commit()

    async def _clear_previous_run(self, tenant_id: str) -> None:
        """Remove any previous reconciliation results for this tenant."""
        await self.session.execute(
            text("DELETE FROM reconciliation_results WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await self.session.execute(
            text("DELETE FROM reconciliation_runs WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await self.session.commit()

    async def _ensure_tables(self) -> None:
        """Create reconciliation output tables if they don't exist.

        Also adds new columns (observed_entity_count, observed_edge_count)
        if the table was created by an older version of the engine.
        """
        await self.session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    triggered_by TEXT DEFAULT 'manual',
                    status TEXT DEFAULT 'running',
                    total_divergences TEXT,
                    dark_nodes TEXT DEFAULT '0',
                    phantom_nodes TEXT DEFAULT '0',
                    identity_mutations TEXT DEFAULT '0',
                    dark_attributes TEXT DEFAULT '0',
                    dark_edges TEXT DEFAULT '0',
                    phantom_edges TEXT DEFAULT '0',
                    cmdb_entity_count TEXT DEFAULT '0',
                    observed_entity_count TEXT DEFAULT '0',
                    cmdb_edge_count TEXT DEFAULT '0',
                    observed_edge_count TEXT DEFAULT '0',
                    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMPTZ
                )
                """
            )
        )
        # Migrate old schema: add observed_* columns if missing (from v1 schema)
        for col, default in [
            ("observed_entity_count", "'0'"),
            ("observed_edge_count", "'0'"),
        ]:
            await self.session.execute(
                text(
                    f"ALTER TABLE reconciliation_runs "
                    f"ADD COLUMN IF NOT EXISTS {col} TEXT DEFAULT {default}"
                )
            )

        await self.session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_results (
                    result_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    divergence_type TEXT NOT NULL,
                    entity_or_relationship TEXT,
                    target_id TEXT,
                    target_type TEXT,
                    domain TEXT,
                    description TEXT,
                    attribute_name TEXT,
                    cmdb_value TEXT,
                    observed_value TEXT,
                    confidence FLOAT DEFAULT 1.0,
                    extra JSONB,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        # Migrate old schema: add observed_value column if missing (from v1 schema)
        await self.session.execute(
            text(
                "ALTER TABLE reconciliation_results "
                "ADD COLUMN IF NOT EXISTS observed_value TEXT"
            )
        )
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_tenant ON reconciliation_results(tenant_id)"
            )
        )
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_type ON reconciliation_results(divergence_type)"
            )
        )
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_domain ON reconciliation_results(domain)"
            )
        )
        await self.session.commit()
