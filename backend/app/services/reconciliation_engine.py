"""
ReconciliationEngine — Signal-based divergence detection service.

Detects CMDB inconsistencies by cross-referencing the declared topology
(network_entities, topology_relationships) against operational signals:

  - KPI telemetry   (kpi_metrics)        — on metrics DB (TimescaleDB)
  - Alarms/events   (telco_events_alarms) — on main DB
  - Neighbour rels   (neighbour_relations) — on main DB

DUAL-DATABASE ARCHITECTURE:
  Main DB   (pedkai, port 5432):  network_entities, topology_relationships,
                                   telco_events_alarms, neighbour_relations,
                                   reconciliation_runs, reconciliation_results
  Metrics DB (pedkai_metrics, 5433): kpi_metrics (57M rows, TimescaleDB)

  Column naming:
    Main DB kpi_metrics:    tags (jsonb), value (float)        — ~1K rows, unused
    Metrics DB kpi_metrics: metadata (jsonb), metric_value (float) — 57M rows

  All kpi_metrics queries go through self._fetch_metrics() / self._scalar_metrics().
  All other tables go through self._fetch() / self._scalar().
  Cross-DB JOINs are impossible — correlations are done in Python.

NO ground-truth tables are accessed. Detection is pure inference:

  - Dark Nodes         : Entity seen in telemetry/alarms but absent from CMDB
  - Phantom Nodes      : CMDB entity with zero operational footprint
  - Identity Mutations : Hardware fingerprint swap, site-ID drift, or ID collision
  - Dark Attributes    : KPI metadata contradicts CMDB-declared attributes
  - Dark Edges         : Neighbour relation exists but no CMDB topology edge
  - Phantom Edges      : CMDB topology edge where neither endpoint shows activity
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
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

# Entity types that are expected to independently emit operational signals
# (KPI telemetry, alarms, or appear in neighbour relations).
# Passive/infrastructure components (cabinets, antennas, cables, power supplies,
# etc.) never emit telemetry on their own — flagging them as "phantom" is noise.
# Only SIGNAL_EMITTING_TYPES are candidates for phantom node detection.
SIGNAL_EMITTING_TYPES = frozenset({
    # RAN active elements
    "LTE_CELL", "NR_CELL", "ENODEB", "GNODEB", "GNODEB_DU",
    "GNODEB_CU_CP", "GNODEB_CU_UP",
    # Transport / routing
    "PE_ROUTER", "P_ROUTER", "CE_ROUTER", "AGGREGATION_SWITCH",
    "ACCESS_SWITCH", "ROUTE_REFLECTOR", "BNG",
    # Fixed access — OLT only; ONT is CPE (telemetry aggregated at OLT)
    "OLT",
    # Core network elements
    "MME", "SGW", "PGW", "AMF", "SMF", "UPF", "UDM", "PCF",
    "NSSF", "HSS", "NWDAF",
    # Optical / transport links
    "MICROWAVE_LINK", "DWDM_SYSTEM",
    # Services that should have traffic evidence
    "LSP", "L3VPN", "L2VPN", "ETHERNET_CIRCUIT", "PSEUDOWIRE",
})

# Entity types that are passive infrastructure — they never emit telemetry
# independently.  Edges connecting only passive types should not be flagged
# as phantom (absence of telemetry is expected, not a CMDB defect).
PASSIVE_ENTITY_TYPES = frozenset({
    # Enclosures & physical structures
    "CABINET", "RACK", "SHELTER", "TOWER", "EXCHANGE_BUILDING",
    # Power infrastructure
    "POWER_SUPPLY", "BATTERY_BANK", "POWER_DISTRIBUTION",
    "SURGE_PROTECTOR", "RECTIFIER", "UPS", "MAINS_CONNECTION", "GENERATOR",
    # Cooling / environmental
    "CLIMATE_CONTROL",
    # RF passive elements
    "ANTENNA", "ANTENNA_SYSTEM", "CABLE", "FEEDER_CABLE", "FIBRE_CABLE",
    "FIBER_PATCH_PANEL",
    # Passive optical / positioning
    "GPS_RECEIVER", "SPLITTER",
    # Logical groupings (no independent telemetry)
    "SITE", "SERVICE_AREA", "TRACKING_AREA",
    # CPE — telemetry aggregated at OLT, not per-ONT
    "ONT", "NTE",
    # Passive optical network elements
    "PON_PORT",
    # Other non-emitting
    "TRANSMISSION_EQUIPMENT", "OPTICAL_CHANNEL",
    "RESIDENTIAL_SERVICE", "ENTERPRISE_SERVICE", "QOS_PROFILE",
})

# Relationship types that represent passive/static infrastructure links.
# These are physical/environmental associations where telemetry flow is
# not expected (e.g. CABINET houses EQUIPMENT, POWER_SUPPLY feeds BATTERY).
PASSIVE_RELATIONSHIP_TYPES = frozenset({
    "HOUSES", "POWERS", "COOLS", "CONTAINS", "MOUNTED_ON",
    "FEEDS", "SHELTERS", "RACK_MOUNT", "GROUNDS", "PROTECTS",
})

# Batch size for bulk inserts
BATCH_SIZE = 2000

# --- Dark-attribute detection controls -------------------------------------
# _detect_dark_attributes scans the kpi_metrics hypertable (tens of millions of
# rows) three times. These knobs make it operable at scale without hanging a run:
#   * ENABLED: allow disabling the whole step for immediate relief.
#   * WINDOW_DAYS: bound the scan to the most recent N days *of the tenant's data*
#       (partition pruning). 0 = unbounded (original semantics). NOTE: the window
#       is anchored to the data's own MAX(timestamp), not wall-clock now — the
#       demo datasets are ~900 days old, so a now-relative window would match
#       nothing. vendor/band/rat_type are static, so a recent slice is sufficient.
#   * TIMEOUT_MS: per-query statement_timeout so a pathological scan fails fast
#       instead of hanging forever (the run stays non-blank thanks to the swap).
DARK_ATTRIBUTES_ENABLED = os.environ.get("RECONCILE_DARK_ATTRIBUTES_ENABLED", "true").lower() == "true"
DARK_ATTRIBUTES_WINDOW_DAYS = int(os.environ.get("RECONCILE_DARK_ATTRIBUTES_WINDOW_DAYS", "0"))
DARK_ATTRIBUTES_TIMEOUT_MS = int(os.environ.get("RECONCILE_DARK_ATTRIBUTES_TIMEOUT_MS", "120000"))

# --- Identity-mutation detection controls (same rationale as dark_attributes:
# it also runs unbounded JSONB GROUP-BY scans over the KPI hypertable). --------
IDENTITY_MUTATIONS_ENABLED = os.environ.get("RECONCILE_IDENTITY_MUTATIONS_ENABLED", "true").lower() == "true"
IDENTITY_MUTATIONS_WINDOW_DAYS = int(os.environ.get("RECONCILE_IDENTITY_MUTATIONS_WINDOW_DAYS", "0"))
IDENTITY_MUTATIONS_TIMEOUT_MS = int(os.environ.get("RECONCILE_IDENTITY_MUTATIONS_TIMEOUT_MS", "120000"))


def _make_result_id(*parts: str) -> str:
    """Deterministic ID from components — idempotent across runs."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


def compute_peer_coverage(
    entities_by_type: dict[str, list[str]],
    active_ids: set[str],
) -> dict[str, float]:
    """Compute per-type peer signal coverage.

    Phantom detection infers absence-of-signal, which conflates a genuinely
    decommissioned entity with one whose telemetry we simply never loaded.
    Peer coverage quantifies how much of a type's population *does* emit
    signal: if a type's peers are broadly active, an inactive member is a
    stronger phantom candidate; if almost none of its peers are active, the
    absence is more likely a data-loading gap than a real divergence.

    For type T:
        coverage(T) = |{entities of type T} ∩ active_ids| / |{entities of type T}|

    Args:
        entities_by_type: mapping of entity_type -> list of entity ids of that type.
        active_ids: union of entity ids observed in operational signals.

    Returns:
        mapping of entity_type -> coverage float in [0.0, 1.0]. A type with an
        empty id list yields 0.0 (no basis to trust the population).
    """
    coverage: dict[str, float] = {}
    for etype, ids in entities_by_type.items():
        total = len(ids)
        if total == 0:
            coverage[etype] = 0.0
            continue
        n_active = sum(1 for eid in ids if eid in active_ids)
        coverage[etype] = n_active / total
    return coverage


class ReconciliationEngine:
    """
    Infers CMDB divergences from operational signals only.

    Data sources used (all operational):
      Main DB:
        - network_entities          (CMDB declared entities)
        - topology_relationships    (CMDB declared edges)
        - telco_events_alarms       (alarm/event feed)
        - neighbour_relations       (cell-to-cell neighbour data)
      Metrics DB:
        - kpi_metrics               (telemetry time-series, 57M rows)

    Usage:
        engine = ReconciliationEngine(db_session, metrics_session)
        summary = await engine.run(tenant_id="pedkai_telco2_01")
    """

    def __init__(self, session: AsyncSession, metrics_session: AsyncSession):
        self.session = session              # main DB (pedkai, port 5432)
        self.metrics_session = metrics_session  # metrics DB (pedkai_metrics, port 5433)
        self.run_id: str = ""
        self.tenant_id: str = ""
        # Distinct entity_ids seen in operational signals, computed ONCE per run
        # (the DISTINCT scans over the ~87M-row KPI hypertable dominate runtime)
        # and reused by every detector. Populated at the start of run().
        self._kpi_active: set[str] = set()
        self._alarm_active: set[str] = set()

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
            # Build the new run in a staging table; the live results are left
            # untouched until the atomic swap at the end. A slow/failed run can
            # therefore never blank the divergence dataset.
            await self._prepare_staging(tenant_id)

            # --- Operational inventory ---
            cmdb_entity_count = await self._scalar(
                "SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            cmdb_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )

            # Distinct entities seen in operational signals (split-DB). Fetch the
            # ID sets ONCE here and cache them on self; every detector reuses them
            # instead of re-scanning the KPI hypertable. Counts are derived from
            # the sets (no separate COUNT(DISTINCT) scans).
            kpi_ids_rows = await self._fetch_metrics(
                "SELECT DISTINCT entity_id FROM kpi_metrics WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            alarm_ids_rows = await self._fetch(
                "SELECT DISTINCT entity_id FROM telco_events_alarms WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            self._kpi_active = {r["entity_id"] for r in kpi_ids_rows}
            self._alarm_active = {r["entity_id"] for r in alarm_ids_rows}
            kpi_entity_count = len(self._kpi_active)
            alarm_entity_count = len(self._alarm_active)
            all_observed_ids = self._kpi_active | self._alarm_active
            observed_entity_count = len(all_observed_ids)

            # Count distinct neighbour-relation edges (main DB)
            observed_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM neighbour_relations WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )

            # --- Detection ---
            counts: dict[str, int] = {}
            counts["dark_nodes"] = await self._detect_dark_nodes(all_observed_ids)
            counts["phantom_nodes"] = await self._detect_phantom_nodes(all_observed_ids)
            # identity_mutations also runs heavy KPI hypertable scans — gate it
            # and make it best-effort for the same reason as dark_attributes.
            if IDENTITY_MUTATIONS_ENABLED:
                try:
                    counts["identity_mutations"] = await self._detect_identity_mutations()
                except Exception as exc:
                    logger.error(
                        "[Reconciliation] identity_mutations detection failed "
                        "(continuing without it): %s", exc, exc_info=True,
                    )
                    await self.metrics_session.rollback()
                    counts["identity_mutations"] = 0
            else:
                logger.info("[Reconciliation] identity_mutations detection disabled via env; skipping")
                counts["identity_mutations"] = 0
            # dark_attributes scans the KPI hypertable and is the heaviest step;
            # gate it and make it best-effort so a slow/timed-out scan degrades
            # to "0 dark attributes" rather than blocking the whole run.
            if DARK_ATTRIBUTES_ENABLED:
                try:
                    counts["dark_attributes"] = await self._detect_dark_attributes()
                except Exception as exc:
                    logger.error(
                        "[Reconciliation] dark_attributes detection failed "
                        "(continuing without it): %s", exc, exc_info=True,
                    )
                    await self.metrics_session.rollback()
                    counts["dark_attributes"] = 0
            else:
                logger.info("[Reconciliation] dark_attributes detection disabled via env; skipping")
                counts["dark_attributes"] = 0
            counts["dark_edges"] = await self._detect_dark_edges()
            counts["phantom_edges"] = await self._detect_phantom_edges()

            shadow_count = await self._populate_shadow_topology()

            total = sum(counts.values())

            completed_at = datetime.now(timezone.utc)
            duration_s = (completed_at - started_at).total_seconds()

            # --- Atomic swap: replace the live results with the freshly-built
            # staging set, and write run metadata, in a SINGLE transaction.
            # The live dataset is only cleared once the new data is ready, so a
            # slow or failed run can never leave the divergence page blank.
            await self.session.execute(
                text("DELETE FROM reconciliation_results WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await self.session.execute(
                text(
                    """
                    INSERT INTO reconciliation_results (
                        result_id, tenant_id, run_id, divergence_type,
                        entity_or_relationship, target_id, target_type, domain,
                        description, attribute_name, cmdb_value, observed_value,
                        confidence, extra, created_at
                    )
                    SELECT
                        result_id, tenant_id, run_id, divergence_type,
                        entity_or_relationship, target_id, target_type, domain,
                        description, attribute_name, cmdb_value, observed_value,
                        confidence, extra, created_at
                    FROM reconciliation_results_staging
                    WHERE tenant_id = :tid
                    """
                ),
                {"tid": tenant_id},
            )

            # --- Persist run metadata (main DB) ---
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
            # Drop older runs' metadata now that this run is the live one —
            # part of the same atomic commit as the results swap above.
            await self.session.execute(
                text(
                    "DELETE FROM reconciliation_runs "
                    "WHERE tenant_id = :tid AND run_id != :run_id"
                ),
                {"tid": tenant_id, "run_id": self.run_id},
            )
            await self.session.commit()

            # Best-effort staging cleanup (outside the critical swap transaction;
            # a failure here cannot affect the now-live results).
            try:
                await self.session.execute(
                    text("DELETE FROM reconciliation_results_staging WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
                await self.session.commit()
            except Exception as exc:
                logger.warning("[Reconciliation] staging cleanup failed (non-fatal): %s", exc)

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

    async def _detect_dark_nodes(self, all_observed_ids: set[str]) -> int:
        """
        Dark nodes: entities observed in telemetry or alarms but absent
        from the CMDB.  These are real network elements carrying traffic
        that the CMDB does not know about.

        Signal sources: kpi_metrics (metrics DB), telco_events_alarms (main DB)
        CMDB reference: network_entities (main DB)

        Split-DB approach:
          1. all_observed_ids already collected (KPI + alarm entity_ids)
          2. Fetch all CMDB entity identifiers from main DB
          3. Subtract to find dark nodes
          4. Look up domain info from KPI metadata on metrics DB
        """
        logger.info("[Reconciliation] Detecting dark nodes from operational signals...")

        # Step 1: Get all CMDB identifiers (both id and external_id)
        cmdb_rows = await self._fetch(
            """
            SELECT CAST(id AS TEXT) AS cmdb_id, external_id
            FROM network_entities
            WHERE tenant_id = :tid
            """,
            {"tid": self.tenant_id},
        )
        cmdb_ids = set()
        for r in cmdb_rows:
            cmdb_ids.add(r["cmdb_id"])
            if r["external_id"]:
                cmdb_ids.add(r["external_id"])

        # Step 2: Find entity_ids in signals but not in CMDB
        dark_ids = all_observed_ids - cmdb_ids

        if not dark_ids:
            logger.info("  -> 0 dark nodes")
            return 0

        # Step 3: Get domain info for dark entities from KPI metadata (metrics DB)
        # Build a lookup: entity_id -> domain
        domain_lookup: dict[str, str] = {}
        source_lookup: dict[str, str] = {}

        # Check which dark_ids are in KPI vs alarms
        kpi_dark = []
        alarm_dark = []

        # Query KPI domains in batches
        dark_list = list(dark_ids)
        for i in range(0, len(dark_list), 500):
            batch = dark_list[i:i + 500]
            placeholders = ", ".join(f":eid_{j}" for j in range(len(batch)))
            params = {"tid": self.tenant_id}
            params.update({f"eid_{j}": eid for j, eid in enumerate(batch)})

            kpi_rows = await self._fetch_metrics(
                f"""
                SELECT entity_id, metadata->>'domain' AS domain
                FROM kpi_metrics
                WHERE tenant_id = :tid
                  AND entity_id IN ({placeholders})
                GROUP BY entity_id, metadata->>'domain'
                """,
                params,
            )
            for r in kpi_rows:
                domain_lookup[r["entity_id"]] = r["domain"]
                source_lookup.setdefault(r["entity_id"], "kpi_telemetry")

            alarm_rows = await self._fetch(
                f"""
                SELECT entity_id, domain
                FROM telco_events_alarms
                WHERE tenant_id = :tid
                  AND entity_id IN ({placeholders})
                GROUP BY entity_id, domain
                """,
                params,
            )
            for r in alarm_rows:
                if r["entity_id"] not in domain_lookup and r["domain"]:
                    domain_lookup[r["entity_id"]] = r["domain"]
                if r["entity_id"] in source_lookup:
                    source_lookup[r["entity_id"]] += ", alarm_feed"
                else:
                    source_lookup[r["entity_id"]] = "alarm_feed"

        records = [
            {
                "result_id": _make_result_id(self.tenant_id, "dark_node", eid),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "dark_node",
                "entity_or_relationship": "entity",
                "target_id": eid,
                "target_type": "UNKNOWN",
                "domain": domain_lookup.get(eid),
                "description": (
                    f"Entity '{eid}' observed in operational signals "
                    f"({source_lookup.get(eid, 'signals')}) but absent from CMDB. "
                    f"Likely an unregistered network element."
                ),
                "confidence": 0.85,
                "extra": {
                    "signal_source": source_lookup.get(eid, "signals"),
                    "signal_id": eid,
                },
            }
            for eid in dark_ids
        ]
        await self._bulk_insert(records)
        logger.info(f"  -> {len(records):,} dark nodes")
        return len(records)

    async def _detect_phantom_nodes(self, all_observed_ids: set[str]) -> int:
        """
        Phantom nodes: CMDB entities with zero operational footprint.
        No KPI telemetry, no alarms, no neighbour relations reference them.

        Signal sources: kpi_metrics (metrics DB), telco_events_alarms (main DB),
                        neighbour_relations (main DB)
        CMDB reference: network_entities (main DB)

        Split-DB approach:
          1. Get all CMDB entities from main DB
          2. all_observed_ids already has KPI + alarm entity_ids
          3. Also get neighbour_relations entity_ids from main DB
          4. Any CMDB entity not in any signal set is phantom
        """
        logger.info("[Reconciliation] Detecting phantom nodes from signal absence...")

        # Step 1: All CMDB entities
        cmdb_rows = await self._fetch(
            """
            SELECT
                CAST(id AS TEXT) AS entity_id,
                external_id,
                entity_type,
                name,
                attributes->>'domain' AS domain
            FROM network_entities
            WHERE tenant_id = :tid
            """,
            {"tid": self.tenant_id},
        )

        # Step 2: Get neighbour_relations entity_ids (main DB)
        nr_rows = await self._fetch(
            """
            SELECT DISTINCT unnested_id AS entity_id FROM (
                SELECT from_cell_id AS unnested_id FROM neighbour_relations WHERE tenant_id = :tid
                UNION
                SELECT to_cell_id AS unnested_id FROM neighbour_relations WHERE tenant_id = :tid
            ) nr_ids
            """,
            {"tid": self.tenant_id},
        )
        nr_ids = {r["entity_id"] for r in nr_rows}

        # Step 3: Combined signal presence = KPI + alarms + neighbour_relations
        all_signal_ids = all_observed_ids | nr_ids

        # Build a name-based lookup set for additional matching.
        # Signal sources sometimes reference entities by name rather than UUID
        # or external_id — matching on name prevents false phantom detections.
        signal_ids_lower = {sid.lower() for sid in all_signal_ids if sid}

        # Peer signal coverage per entity type.
        # Phantom detection infers from signal absence, which conflates a
        # decommissioned entity with one whose telemetry we simply never
        # loaded. Coverage = fraction of a type's population that *does* emit
        # signal; a low value means the absence is more likely a data gap.
        # Computed from the already-fetched CMDB entity list (no extra query).
        entities_by_type: dict[str, list[str]] = {}
        for r in cmdb_rows:
            entities_by_type.setdefault(r["entity_type"], []).append(r["entity_id"])
        peer_coverage = compute_peer_coverage(entities_by_type, all_signal_ids)
        # Precompute per-type active counts ONCE so the per-record loop below is
        # an O(1) dict lookup, not an O(peers) rescan (phantom scale: ~81K nodes
        # × up to ~50K same-type peers would be billions of membership checks).
        active_count_by_type = {
            et: sum(1 for eid in ids if eid in all_signal_ids)
            for et, ids in entities_by_type.items()
        }
        min_peer_coverage = float(os.environ.get("PHANTOM_MIN_PEER_COVERAGE", "0.2"))

        # Step 4: CMDB entities with no signal presence
        # Only flag entity types that are EXPECTED to emit signals.
        # Passive infrastructure (cabinets, antennas, cables, power supplies)
        # never emit KPI/alarms independently — flagging them is noise.
        records = []
        for r in cmdb_rows:
            etype = r["entity_type"]
            # Skip passive/infrastructure types (explicit blocklist)
            if etype in PASSIVE_ENTITY_TYPES:
                continue
            # Skip types not expected to emit signals (allowlist)
            if etype not in SIGNAL_EMITTING_TYPES:
                continue
            # Check UUID id, external_id, and name against signal sets
            eid = r["entity_id"]
            ext_id = r["external_id"]
            name = r["name"]
            if eid in all_signal_ids:
                continue
            if ext_id and ext_id in all_signal_ids:
                continue
            # Name-based fallback (case-insensitive)
            if name and name.lower() in signal_ids_lower:
                continue
            # Signal-emitting type with no signal presence at all
            # Checked: UUID, external_id, and name (case-insensitive).
            base_conf = 0.75
            cov = peer_coverage.get(etype, 0.0)
            n_total = len(entities_by_type.get(etype, []))
            n_active = active_count_by_type.get(etype, 0)
            confidence = max(0.05, min(base_conf, base_conf * cov))
            extra = {
                "detection_method": "signal_absence",
                "signals_checked": [
                    "kpi_metrics",
                    "telco_events_alarms",
                    "neighbour_relations",
                ],
                "match_keys_checked": ["id", "external_id", "name"],
                "cmdb_entity_type": etype,
                "cmdb_external_id": ext_id,
                "peer_coverage": cov,
                "coverage_basis": f"{etype}:{n_active}/{n_total}",
            }
            if cov < min_peer_coverage:
                extra["low_data_confidence"] = True
            records.append(
                {
                    "result_id": _make_result_id(self.tenant_id, "phantom_node", eid),
                    "tenant_id": self.tenant_id,
                    "run_id": self.run_id,
                    "divergence_type": "phantom_node",
                    "entity_or_relationship": "entity",
                    "target_id": eid,
                    "target_type": r["entity_type"],
                    "domain": r["domain"],
                    "description": (
                        f"CMDB entity {r['name']} ({r['entity_type']}) has no operational "
                        f"footprint — zero KPI samples, zero alarms, zero neighbour "
                        f"relations. May be decommissioned or a phantom CI."
                    ),
                    "confidence": confidence,
                    "extra": extra,
                }
            )

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
           different (vendor, rat_type) pair than the CMDB.

        2. Site-ID drift — KPI metadata reports site_id X for an entity, but
           the CMDB declares the entity belongs to site_id Y.

        3. Multi-entity ID collision — Two or more CMDB entities with different
           UUIDs both have external_ids that map to the same KPI entity_id.

        Split-DB: KPI aggregates fetched from metrics DB, then correlated
        with CMDB data from main DB in Python.
        """
        logger.info("[Reconciliation] Detecting identity mutations from operational signals...")
        all_records: list[dict] = []

        # --- Get CMDB entity info for correlation (main DB) ---
        cmdb_rows = await self._fetch(
            """
            SELECT
                CAST(id AS TEXT) AS entity_id,
                external_id,
                entity_type,
                name,
                attributes->>'domain' AS domain,
                attributes->>'vendor' AS vendor,
                attributes->>'rat_type' AS rat_type,
                attributes->>'site_id' AS site_id
            FROM network_entities
            WHERE tenant_id = :tid
            """,
            {"tid": self.tenant_id},
        )
        # Build lookup: entity_id/external_id/name -> cmdb info
        cmdb_by_id: dict[str, dict] = {}
        cmdb_by_ext: dict[str, dict] = {}
        cmdb_by_name: dict[str, dict] = {}
        for r in cmdb_rows:
            cmdb_by_id[r["entity_id"]] = r
            if r["external_id"]:
                cmdb_by_ext[r["external_id"]] = r
            if r["name"]:
                cmdb_by_name[r["name"]] = r

        def _resolve_cmdb(kpi_entity_id: str) -> dict | None:
            """Resolve a KPI entity_id to CMDB record.

            Tries UUID match, then external_id, then name-based fallback.
            """
            if kpi_entity_id in cmdb_by_id:
                return cmdb_by_id[kpi_entity_id]
            if kpi_entity_id in cmdb_by_ext:
                return cmdb_by_ext[kpi_entity_id]
            # Name-based fallback: KPI entity_id might match CMDB name
            if kpi_entity_id in cmdb_by_name:
                return cmdb_by_name[kpi_entity_id]
            return None

        logger.info(
            f"  [identity_mutation] CMDB lookup sizes: "
            f"by_id={len(cmdb_by_id)}, by_ext={len(cmdb_by_ext)}, by_name={len(cmdb_by_name)}"
        )

        # Fail fast instead of hanging: per-statement timeout on the (per-run)
        # metrics session for the heavy KPI scans below.
        if IDENTITY_MUTATIONS_TIMEOUT_MS > 0:
            await self.metrics_session.execute(
                text(f"SET statement_timeout = {int(IDENTITY_MUTATIONS_TIMEOUT_MS)}")
            )

        # Optionally bound the scans to the most recent window of the tenant's own
        # data (partition pruning); anchored to MAX(timestamp), not now(), because
        # datasets may be historical. vendor/rat_type/site_id are static metadata,
        # so a recent slice yields the same dominant value far more cheaply.
        params: dict = {"tid": self.tenant_id}
        time_clause = ""
        if IDENTITY_MUTATIONS_WINDOW_DAYS > 0:
            max_rows = await self._fetch_metrics(
                "SELECT MAX(timestamp) AS mx FROM kpi_metrics WHERE tenant_id = :tid",
                {"tid": self.tenant_id},
            )
            mx = max_rows[0]["mx"] if max_rows else None
            if mx is not None:
                params["since"] = mx - timedelta(days=IDENTITY_MUTATIONS_WINDOW_DAYS)
                time_clause = "AND timestamp >= :since"

        # --- Strategy 1: Hardware fingerprint swap ---
        # Get dominant (vendor, rat_type) per entity from metrics DB
        hw_rows = await self._fetch_metrics(
            f"""
            WITH telemetry_fingerprint AS (
                SELECT
                    entity_id,
                    metadata->>'vendor'   AS tel_vendor,
                    metadata->>'rat_type' AS tel_rat,
                    COUNT(*) AS sample_count
                FROM kpi_metrics
                WHERE tenant_id = :tid
                  AND metadata->>'vendor' IS NOT NULL
                  AND metadata->>'rat_type' IS NOT NULL
                  {time_clause}
                GROUP BY entity_id, metadata->>'vendor', metadata->>'rat_type'
            ),
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY entity_id ORDER BY sample_count DESC
                    ) AS rn
                FROM telemetry_fingerprint
            )
            SELECT entity_id, tel_vendor, tel_rat, sample_count
            FROM ranked
            WHERE rn = 1
            """,
            params,
        )
        # Correlate with CMDB in Python
        hw_resolved = 0
        hw_with_attrs = 0
        hw_mismatches = 0
        for r in hw_rows:
            cmdb = _resolve_cmdb(r["entity_id"])
            if not cmdb:
                continue  # Not in CMDB — would be a dark_node, not identity_mutation
            hw_resolved += 1
            if not cmdb["vendor"] or not cmdb["rat_type"]:
                continue
            hw_with_attrs += 1
            cmdb_vendor = cmdb["vendor"].strip().lower()
            cmdb_rat = cmdb["rat_type"].strip().lower()
            tel_vendor = (r["tel_vendor"] or "").strip().lower()
            tel_rat = (r["tel_rat"] or "").strip().lower()
            # Both must differ for hw_swap (single-attr is dark_attribute)
            if cmdb_vendor != tel_vendor and cmdb_rat != tel_rat:
                hw_mismatches += 1
                cmdb_fp = f"{cmdb['vendor']}/{cmdb['rat_type']}"
                obs_fp = f"{r['tel_vendor']}/{r['tel_rat']}"
                target_id = cmdb["entity_id"]
                all_records.append(
                    {
                        "result_id": _make_result_id(
                            self.tenant_id, "identity_mutation", "hw_swap", target_id
                        ),
                        "tenant_id": self.tenant_id,
                        "run_id": self.run_id,
                        "divergence_type": "identity_mutation",
                        "entity_or_relationship": "entity",
                        "target_id": target_id,
                        "target_type": cmdb["entity_type"],
                        "domain": cmdb["domain"],
                        "description": (
                            f"Hardware fingerprint swap: {cmdb['name']} ({cmdb['entity_type']}) "
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

        logger.info(
            f"  [identity_mutation] hw_swap: {len(hw_rows)} KPI fingerprints, "
            f"{hw_resolved} resolved to CMDB, {hw_with_attrs} with vendor+rat_type, "
            f"{hw_mismatches} mismatches"
        )

        # --- Strategy 2: Site-ID drift ---
        # Get dominant site_id per entity from metrics DB
        site_rows = await self._fetch_metrics(
            f"""
            WITH tel_site AS (
                SELECT
                    entity_id,
                    metadata->>'site_id' AS tel_site_id,
                    COUNT(*) AS sample_count
                FROM kpi_metrics
                WHERE tenant_id = :tid
                  AND metadata->>'site_id' IS NOT NULL
                  {time_clause}
                GROUP BY entity_id, metadata->>'site_id'
            ),
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY entity_id ORDER BY sample_count DESC
                    ) AS rn
                FROM tel_site
            )
            SELECT entity_id, tel_site_id, sample_count
            FROM ranked
            WHERE rn = 1
            """,
            params,
        )
        # Correlate with CMDB in Python
        site_resolved = 0
        site_with_attr = 0
        site_drifts = 0
        for r in site_rows:
            cmdb = _resolve_cmdb(r["entity_id"])
            if not cmdb:
                continue
            site_resolved += 1
            if not cmdb["site_id"] or not r["tel_site_id"]:
                continue
            site_with_attr += 1
            if cmdb["site_id"] != r["tel_site_id"]:
                site_drifts += 1
                target_id = cmdb["entity_id"]
                all_records.append(
                    {
                        "result_id": _make_result_id(
                            self.tenant_id, "identity_mutation", "site_drift", target_id
                        ),
                        "tenant_id": self.tenant_id,
                        "run_id": self.run_id,
                        "divergence_type": "identity_mutation",
                        "entity_or_relationship": "entity",
                        "target_id": target_id,
                        "target_type": cmdb["entity_type"],
                        "domain": cmdb["domain"],
                        "description": (
                            f"Site-ID drift: {cmdb['name']} ({cmdb['entity_type']}) "
                            f"CMDB says site '{cmdb['site_id']}' but telemetry "
                            f"reports site '{r['tel_site_id']}' "
                            f"({r['sample_count']} samples). Entity may have been "
                            f"physically relocated or re-homed without CMDB update."
                        ),
                        "attribute_name": "site_id",
                        "cmdb_value": cmdb["site_id"],
                        "observed_value": r["tel_site_id"],
                        "confidence": min(0.90, 0.5 + 0.05 * min(r["sample_count"], 8)),
                    }
                )

        logger.info(
            f"  [identity_mutation] site_drift: {len(site_rows)} KPI site entries, "
            f"{site_resolved} resolved to CMDB, {site_with_attr} with site_id, "
            f"{site_drifts} drifts"
        )

        # --- Strategy 3: Multi-entity ID collision ---
        # Reuse the KPI entity_id set computed once in run() (avoids another
        # DISTINCT scan of the KPI hypertable).
        kpi_eid_set = self._kpi_active

        # Find CMDB entities whose external_id matches a KPI entity_id
        # Group by external_id to find collisions (multiple CMDB UUIDs -> same ext_id)
        ext_id_to_cmdb: dict[str, list[dict]] = {}
        for r in cmdb_rows:
            ext_id = r["external_id"]
            if ext_id and ext_id in kpi_eid_set:
                ext_id_to_cmdb.setdefault(ext_id, []).append(r)

        collisions_found = sum(1 for g in ext_id_to_cmdb.values() if len(g) > 1)
        logger.info(
            f"  [identity_mutation] id_collision: {len(kpi_eid_set)} KPI entity_ids, "
            f"{len(ext_id_to_cmdb)} matched CMDB external_ids, "
            f"{collisions_found} collisions"
        )

        for kpi_eid, group in ext_id_to_cmdb.items():
            if len(group) <= 1:
                continue  # No collision
            names = ", ".join(f"{g['name']} ({g['entity_id'][:8]})" for g in group)
            for g in group:
                all_records.append(
                    {
                        "result_id": _make_result_id(
                            self.tenant_id, "identity_mutation", "id_collision",
                            g["entity_id"]
                        ),
                        "tenant_id": self.tenant_id,
                        "run_id": self.run_id,
                        "divergence_type": "identity_mutation",
                        "entity_or_relationship": "entity",
                        "target_id": g["entity_id"],
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

        Signal source: kpi_metrics.metadata (metrics DB)
        CMDB reference: network_entities.attributes (main DB)

        Split-DB: fetch KPI aggregates from metrics DB, correlate with CMDB
        in Python.
        """
        logger.info("[Reconciliation] Detecting dark attributes from KPI metadata...")
        all_records: list[dict] = []

        # Get CMDB entity info (main DB)
        cmdb_rows = await self._fetch(
            """
            SELECT
                CAST(id AS TEXT) AS entity_id,
                external_id,
                entity_type,
                name,
                attributes->>'domain' AS domain,
                attributes
            FROM network_entities
            WHERE tenant_id = :tid
            """,
            {"tid": self.tenant_id},
        )
        # Build lookups
        cmdb_by_id: dict[str, dict] = {}
        cmdb_by_ext: dict[str, dict] = {}
        for r in cmdb_rows:
            cmdb_by_id[r["entity_id"]] = r
            if r["external_id"]:
                cmdb_by_ext[r["external_id"]] = r

        # Fail fast instead of hanging: bound each KPI scan with a per-statement
        # timeout on the (per-run) metrics session. Left set for the rest of the
        # run — harmless, as the other metrics queries are fast.
        if DARK_ATTRIBUTES_TIMEOUT_MS > 0:
            await self.metrics_session.execute(
                text(f"SET statement_timeout = {int(DARK_ATTRIBUTES_TIMEOUT_MS)}")
            )

        # Optionally bound the scan to the most recent window of the tenant's own
        # data (hypertable partition pruning). Anchored to MAX(timestamp), NOT
        # now(), because datasets may be historical (demo data is ~900 days old).
        # vendor/band/rat_type are static entity metadata, so a recent slice
        # yields the same dominant value at a fraction of the scan cost.
        params: dict = {"tid": self.tenant_id}
        time_clause = ""
        if DARK_ATTRIBUTES_WINDOW_DAYS > 0:
            max_rows = await self._fetch_metrics(
                "SELECT MAX(timestamp) AS mx FROM kpi_metrics WHERE tenant_id = :tid",
                {"tid": self.tenant_id},
            )
            mx = max_rows[0]["mx"] if max_rows else None
            if mx is not None:
                params["since"] = mx - timedelta(days=DARK_ATTRIBUTES_WINDOW_DAYS)
                time_clause = "AND timestamp >= :since"

        for attr in CROSSCHECK_ATTRIBUTES:
            # Get per-entity dominant attribute value from KPI (metrics DB)
            kpi_rows = await self._fetch_metrics(
                f"""
                WITH agg AS (
                    SELECT
                        entity_id,
                        metadata->>'{attr}' AS observed_val,
                        COUNT(*) AS sample_count
                    FROM kpi_metrics
                    WHERE tenant_id = :tid
                      AND metadata->>'{attr}' IS NOT NULL
                      {time_clause}
                    GROUP BY entity_id, metadata->>'{attr}'
                ),
                ranked AS (
                    SELECT *,
                        ROW_NUMBER() OVER (
                            PARTITION BY entity_id ORDER BY sample_count DESC
                        ) AS rn
                    FROM agg
                )
                SELECT entity_id, observed_val, sample_count
                FROM ranked
                WHERE rn = 1
                """,  # nosec — attr from hardcoded CROSSCHECK_ATTRIBUTES list
                params,
            )

            # Correlate with CMDB in Python
            for r in kpi_rows:
                eid = r["entity_id"]
                cmdb = cmdb_by_id.get(eid) or cmdb_by_ext.get(eid)
                if not cmdb:
                    continue  # Not in CMDB — dark_node, not dark_attribute

                # Get CMDB value for this attribute
                attrs = cmdb.get("attributes") or {}
                cmdb_val = attrs.get(attr) if isinstance(attrs, dict) else None
                if not cmdb_val:
                    continue  # CMDB doesn't declare this attribute

                observed_val = r["observed_val"]
                if not observed_val:
                    continue

                if cmdb_val.strip().lower() != observed_val.strip().lower():
                    target_id = cmdb["entity_id"]
                    all_records.append(
                        {
                            "result_id": _make_result_id(
                                self.tenant_id, "dark_attribute", target_id, attr
                            ),
                            "tenant_id": self.tenant_id,
                            "run_id": self.run_id,
                            "divergence_type": "dark_attribute",
                            "entity_or_relationship": "entity",
                            "target_id": target_id,
                            "target_type": cmdb["entity_type"],
                            "domain": cmdb["domain"],
                            "description": (
                                f"Attribute '{attr}' conflict: CMDB declares "
                                f"'{cmdb_val}' but telemetry reports "
                                f"'{observed_val}' ({r['sample_count']} samples). "
                                f"Entity: {cmdb['name']} ({cmdb['entity_type']})."
                            ),
                            "attribute_name": attr,
                            "cmdb_value": cmdb_val,
                            "observed_value": observed_val,
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

        Signal source: neighbour_relations (main DB)
        CMDB reference: topology_relationships (main DB)

        Both tables on main DB — single query, no split needed.
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
                        (tr.from_entity_id = CAST(nr.from_cell_id AS TEXT)
                         AND tr.to_entity_id = CAST(nr.to_cell_id AS TEXT))
                        OR
                        (tr.from_entity_id = CAST(nr.to_cell_id AS TEXT)
                         AND tr.to_entity_id = CAST(nr.from_cell_id AS TEXT))
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

        Signal sources: kpi_metrics (metrics DB), telco_events_alarms (main DB)
        CMDB reference: topology_relationships (main DB)

        Split-DB approach:
          1. Get all CMDB edges from main DB
          2. Get active KPI entity_ids from metrics DB
          3. Get active alarm entity_ids from main DB
          4. Edge is phantom if neither endpoint is in any active set
        """
        logger.info("[Reconciliation] Detecting phantom edges from signal absence...")

        # Step 1: All CMDB edges (main DB)
        edges = await self._fetch(
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
            """,
            {"tid": self.tenant_id},
        )

        if not edges:
            logger.info("  -> 0 phantom edges")
            return 0

        # Active entity_ids — reuse the sets computed once in run() rather than
        # re-scanning the KPI hypertable and the alarm table.
        kpi_active = self._kpi_active
        alarm_active = self._alarm_active
        active_ids = kpi_active | alarm_active

        # Peer signal coverage per endpoint entity type.
        # ONE additional query of network_entities, grouped once into a dict,
        # so a phantom edge whose endpoint types are broadly inactive can be
        # downgraded (absence more likely a data-loading gap than a real edge
        # that both endpoints went silent on).
        ne_rows = await self._fetch(
            """
            SELECT CAST(id AS TEXT) AS entity_id, entity_type
            FROM network_entities
            WHERE tenant_id = :tid
            """,
            {"tid": self.tenant_id},
        )
        entities_by_type: dict[str, list[str]] = {}
        for ne in ne_rows:
            entities_by_type.setdefault(ne["entity_type"], []).append(ne["entity_id"])
        peer_coverage = compute_peer_coverage(entities_by_type, active_ids)
        # Precompute per-type active counts ONCE so _coverage_for_types is an
        # O(1) lookup per phantom edge (~140K edges) rather than an O(peers) rescan.
        active_count_by_type = {
            et: sum(1 for eid in ids if eid in active_ids)
            for et, ids in entities_by_type.items()
        }
        min_peer_coverage = float(os.environ.get("PHANTOM_MIN_PEER_COVERAGE", "0.2"))

        def _coverage_for_types(*types: str) -> tuple[str, float, int, int]:
            """Pick the endpoint type with the most trustworthy (highest)
            coverage; that is the strongest evidence the edge should be live.
            Returns (basis_type, coverage, n_active, n_total)."""
            best_type = None
            best_cov = -1.0
            for t in types:
                if not t:
                    continue
                cov = peer_coverage.get(t)
                if cov is None:
                    continue
                if cov > best_cov:
                    best_cov = cov
                    best_type = t
            if best_type is None:
                # No CMDB population for either endpoint type — treat as 0.0
                basis_type = next((t for t in types if t), "UNKNOWN")
                return basis_type, 0.0, 0, 0
            n_total = len(entities_by_type.get(best_type, []))
            n_active = active_count_by_type.get(best_type, 0)
            return best_type, best_cov, n_active, n_total

        # Step 4: Edge is phantom if NEITHER endpoint is active
        # Skip passive infrastructure relationships where telemetry absence
        # is expected (e.g. CABINET→CLIMATE_CONTROL, POWER_SUPPLY→BATTERY_BANK).
        records = []
        skipped_passive = 0
        for r in edges:
            # Skip passive relationship types (HOUSES, POWERS, COOLS, etc.)
            if r["rel_type"] and r["rel_type"].upper() in PASSIVE_RELATIONSHIP_TYPES:
                skipped_passive += 1
                continue
            # Skip edges where both endpoints are passive infrastructure
            from_type = (r["from_type"] or "").upper()
            to_type = (r["to_type"] or "").upper()
            if from_type in PASSIVE_ENTITY_TYPES and to_type in PASSIVE_ENTITY_TYPES:
                skipped_passive += 1
                continue
            from_active = r["from_id"] in active_ids
            to_active = r["to_id"] in active_ids
            if not from_active and not to_active:
                base_conf = 0.70
                basis_type, cov, n_active, n_total = _coverage_for_types(
                    r["from_type"], r["to_type"]
                )
                confidence = max(0.05, min(base_conf, base_conf * cov))
                extra = {
                    "peer_coverage": cov,
                    "coverage_basis": f"{basis_type}:{n_active}/{n_total}",
                }
                if cov < min_peer_coverage:
                    extra["low_data_confidence"] = True
                records.append(
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
                        "confidence": confidence,
                        "extra": extra,
                    }
                )

        await self._bulk_insert(records)
        logger.info(
            f"  -> {len(records):,} phantom edges "
            f"({skipped_passive:,} passive infrastructure edges excluded)"
        )
        return len(records)

    async def _populate_shadow_topology(self) -> int:
        """
        Post-reconciliation: create shadow entities for dark nodes and
        shadow relationships for dark edges. These populate Pedkai's
        private topology graph for inferred network intelligence.
        """
        logger.info("[Reconciliation] Populating shadow topology from divergence results...")
        created = 0

        # Create shadow entities for dark nodes
        dark_nodes = await self._fetch(
            """
            SELECT target_id, domain, description, confidence,
                   extra->>'signal_source' AS signal_source
            FROM reconciliation_results
            WHERE tenant_id = :tid AND run_id = :rid AND divergence_type = 'dark_node'
            """,
            {"tid": self.tenant_id, "rid": self.run_id},
        )

        for dn in dark_nodes:
            try:
                await self.session.execute(
                    text(
                        """
                        INSERT INTO shadow_entity (
                            id, tenant_id, entity_identifier, entity_domain,
                            origin, enrichment_value, first_seen, last_evidence
                        ) VALUES (
                            :id, :tid, :ident, :domain,
                            'PEDKAI_DISCOVERED', :confidence, NOW(), NOW()
                        )
                        ON CONFLICT (tenant_id, entity_identifier) DO UPDATE
                        SET enrichment_value = EXCLUDED.enrichment_value,
                            last_evidence = NOW()
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tid": self.tenant_id,
                        "ident": dn["target_id"],
                        "domain": dn.get("domain"),
                        "confidence": float(dn.get("confidence", 0.85)),
                    },
                )
                created += 1
            except Exception as e:
                logger.debug(f"Shadow entity insert skipped for {dn['target_id']}: {e}")

        # Create shadow relationships for dark edges
        dark_edges = await self._fetch(
            """
            SELECT rr.target_id, rr.confidence,
                   nr.from_cell_id, nr.to_cell_id, nr.neighbour_type
            FROM reconciliation_results rr
            LEFT JOIN neighbour_relations nr
              ON nr.relation_id = rr.target_id AND nr.tenant_id = :tid
            WHERE rr.tenant_id = :tid AND rr.run_id = :rid
              AND rr.divergence_type = 'dark_edge'
              AND nr.from_cell_id IS NOT NULL
            """,
            {"tid": self.tenant_id, "rid": self.run_id},
        )

        for de in dark_edges:
            try:
                # Ensure both endpoints exist as shadow entities
                for endpoint_id in [de["from_cell_id"], de["to_cell_id"]]:
                    await self.session.execute(
                        text(
                            """
                            INSERT INTO shadow_entity (
                                id, tenant_id, entity_identifier, origin,
                                enrichment_value, first_seen, last_evidence
                            ) VALUES (
                                :id, :tid, :ident, 'CMDB_DECLARED',
                                0.0, NOW(), NOW()
                            )
                            ON CONFLICT (tenant_id, entity_identifier) DO NOTHING
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "tid": self.tenant_id,
                            "ident": endpoint_id,
                        },
                    )

                # Get shadow entity IDs
                from_se = await self.session.execute(
                    text(
                        "SELECT id FROM shadow_entity WHERE tenant_id = :tid AND entity_identifier = :ident"
                    ),
                    {"tid": self.tenant_id, "ident": de["from_cell_id"]},
                )
                to_se = await self.session.execute(
                    text(
                        "SELECT id FROM shadow_entity WHERE tenant_id = :tid AND entity_identifier = :ident"
                    ),
                    {"tid": self.tenant_id, "ident": de["to_cell_id"]},
                )
                from_id = from_se.scalar()
                to_id = to_se.scalar()

                if from_id and to_id:
                    await self.session.execute(
                        text(
                            """
                            INSERT INTO shadow_relationship (
                                id, tenant_id, from_entity_id, to_entity_id,
                                relationship_type, confidence, evidence_summary,
                                exported_to_cmdb, discovered_at
                            ) VALUES (
                                :id, :tid, :from_id, :to_id,
                                :rel_type, :confidence, :evidence,
                                false, NOW()
                            )
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "tid": self.tenant_id,
                            "from_id": from_id,
                            "to_id": to_id,
                            "rel_type": de.get("neighbour_type", "INFERRED_NEIGHBOUR"),
                            "confidence": float(de.get("confidence", 0.75)),
                            "evidence": json.dumps({
                                "source": "reconciliation_engine",
                                "run_id": self.run_id,
                                "neighbour_relation_id": de["target_id"],
                            }),
                        },
                    )
                    created += 1
            except Exception as e:
                logger.debug(f"Shadow relationship insert skipped: {e}")

        await self.session.commit()
        logger.info(f"  -> {created} shadow topology entries created/updated")
        return created

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def _fetch(self, sql: str, params: dict) -> list[dict]:
        """Execute query against main DB (pedkai)."""
        result = await self.session.execute(text(sql), params)
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]

    async def _fetch_metrics(self, sql: str, params: dict) -> list[dict]:
        """Execute query against metrics DB (pedkai_metrics / TimescaleDB)."""
        result = await self.metrics_session.execute(text(sql), params)
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]

    async def _scalar(self, sql: str, params: dict) -> int:
        """Execute scalar query against main DB."""
        result = await self.session.execute(text(sql), params)
        val = result.scalar()
        return int(val) if val is not None else 0

    async def _scalar_metrics(self, sql: str, params: dict) -> int:
        """Execute scalar query against metrics DB."""
        result = await self.metrics_session.execute(text(sql), params)
        val = result.scalar()
        return int(val) if val is not None else 0

    async def _bulk_insert(self, records: list[dict]) -> None:
        if not records:
            return
        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            # Detectors write into the STAGING table; the live results table is
            # only replaced by the atomic swap at the end of run().
            await self.session.execute(
                text(
                    """
                    INSERT INTO reconciliation_results_staging (
                        result_id, tenant_id, run_id, divergence_type,
                        entity_or_relationship, target_id, target_type, domain,
                        description, attribute_name, cmdb_value, observed_value,
                        confidence, extra
                    ) VALUES (
                        :result_id, :tenant_id, :run_id, :divergence_type,
                        :entity_or_relationship, :target_id, :target_type, :domain,
                        :description, :attribute_name, :cmdb_value, :observed_value,
                        :confidence, :extra
                    )
                    ON CONFLICT (result_id) DO NOTHING
                    """
                ),
                [
                    {
                        "attribute_name": r.get("attribute_name"),
                        "cmdb_value": r.get("cmdb_value"),
                        "observed_value": r.get("observed_value"),
                        "extra": json.dumps(r["extra"]) if r.get("extra") else None,
                        **{k: v for k, v in r.items() if k != "extra"},
                    }
                    for r in chunk
                ],
            )
            await self.session.commit()

    async def _prepare_staging(self, tenant_id: str) -> None:
        """Clear only the STAGING table for this tenant before a new run.

        The live ``reconciliation_results`` / ``reconciliation_runs`` are left
        untouched here — they are replaced atomically by the swap at the end of
        ``run()`` once the new data is fully built. This guarantees a slow or
        failed run never leaves the divergence dataset blank.
        """
        await self.session.execute(
            text("DELETE FROM reconciliation_results_staging WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await self.session.commit()

    async def _ensure_tables(self) -> None:
        """Create reconciliation output tables if they don't exist."""
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
        await self.session.execute(
            text(
                "ALTER TABLE reconciliation_results "
                "ADD COLUMN IF NOT EXISTS observed_value TEXT"
            )
        )
        await self.session.execute(
            text(
                "ALTER TABLE reconciliation_results "
                "ADD COLUMN IF NOT EXISTS ai_analysis JSONB"
            )
        )
        # `extra` (PRV-03 peer-coverage annotations, read by the divergence UI)
        # is only in the CREATE above — add it explicitly so pre-existing
        # deployments whose table predates the column also get it.
        await self.session.execute(
            text(
                "ALTER TABLE reconciliation_results "
                "ADD COLUMN IF NOT EXISTS extra JSONB"
            )
        )
        # Staging table for the build-then-atomic-swap write path. Mirrors the
        # live table (including the ALTER-added columns) so the swap INSERT..SELECT
        # is column-compatible.
        await self.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS reconciliation_results_staging "
                "(LIKE reconciliation_results INCLUDING DEFAULTS)"
            )
        )
        # LIKE ... INCLUDING DEFAULTS copies columns but NOT the primary key, so
        # _bulk_insert's `ON CONFLICT (result_id) DO NOTHING` needs an explicit
        # unique index on result_id. Creating it IF NOT EXISTS also self-heals
        # any staging table created by an earlier build that lacked it.
        await self.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_rr_staging_result_id "
                "ON reconciliation_results_staging(result_id)"
            )
        )
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_staging_tenant "
                "ON reconciliation_results_staging(tenant_id)"
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
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_tenant_type_domain ON reconciliation_results(tenant_id, divergence_type, domain)"
            )
        )
        await self.session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rr_tenant_confidence ON reconciliation_results(tenant_id, confidence DESC)"
            )
        )
        await self.session.commit()
