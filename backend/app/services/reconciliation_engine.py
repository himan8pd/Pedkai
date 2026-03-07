"""
ReconciliationEngine — Core Dark Graph divergence detection service.

Compares CMDB declared state (network_entities, topology_relationships)
against ground truth reality (gt_network_entities, gt_entity_relationships)
using SQL set-difference operations to algorithmically discover:

  - Dark Nodes      : In reality, absent from CMDB
  - Phantom Nodes   : In CMDB, absent from reality
  - Identity Mutations : Present in both, but external_id drifted
  - Dark Attributes : Present in both, but attribute values wrong in CMDB
  - Dark Edges      : In reality, absent from CMDB
  - Phantom Edges   : In CMDB, absent from reality

After detection, scores the engine's findings against the pre-seeded
divergence_manifest (ground truth labels) to compute precision/recall/F1.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Attributes from the JSONB column to compare for dark_attribute detection
COMPARABLE_ATTRIBUTES = [
    "vendor",
    "band",
    "sla_tier",
    "rat_type",
    "deployment_profile",
    "max_tx_power_dbm",
    "max_prbs",
    "frequency_mhz",
]

# Page size for batch inserts
BATCH_SIZE = 2000


def _make_result_id(*parts: str) -> str:
    """Deterministic ID from components — idempotent across runs."""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


class ReconciliationEngine:
    """
    Compares CMDB intent against ground truth reality.

    Usage:
        engine = ReconciliationEngine(db_session)
        run_summary = await engine.run(tenant_id="pedkai_telco2_01")
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.run_id: str = ""
        self.tenant_id: str = ""

    async def run(self, tenant_id: str) -> dict[str, Any]:
        """
        Execute full reconciliation. Returns run summary dict.
        Called by the API endpoint POST /divergence/run.
        """
        self.tenant_id = tenant_id
        self.run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        logger.info(f"[Reconciliation] Starting run {self.run_id} for tenant {tenant_id}")

        try:
            await self._ensure_tables()
            await self._clear_previous_run(tenant_id)

            # --- Entity counts ---
            cmdb_count = await self._scalar(
                "SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            gt_count = await self._scalar(
                "SELECT COUNT(*) FROM gt_network_entities WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            confirmed_count = await self._scalar(
                """
                SELECT COUNT(*)
                FROM network_entities ne
                JOIN gt_network_entities gt
                  ON gt.entity_id = CAST(ne.id AS TEXT) AND gt.tenant_id = ne.tenant_id
                WHERE ne.tenant_id = :tid
                """,
                {"tid": tenant_id},
            )

            # --- Edge counts ---
            cmdb_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            gt_edge_count = await self._scalar(
                "SELECT COUNT(*) FROM gt_entity_relationships WHERE tenant_id = :tid",
                {"tid": tenant_id},
            )
            confirmed_edge_count = await self._scalar(
                """
                SELECT COUNT(*)
                FROM topology_relationships tr
                JOIN gt_entity_relationships gt
                  ON gt.from_entity_id = tr.from_entity_id
                 AND gt.to_entity_id   = tr.to_entity_id
                 AND gt.relationship_type = tr.relationship_type
                 AND gt.tenant_id = tr.tenant_id
                WHERE tr.tenant_id = :tid
                """,
                {"tid": tenant_id},
            )

            # --- Detect all divergence types ---
            counts = {}
            counts["dark_nodes"] = await self._detect_dark_nodes()
            counts["phantom_nodes"] = await self._detect_phantom_nodes()
            counts["identity_mutations"] = await self._detect_identity_mutations()
            counts["dark_attributes"] = await self._detect_dark_attributes()
            counts["dark_edges"] = await self._detect_dark_edges()
            counts["phantom_edges"] = await self._detect_phantom_edges()

            total = sum(counts.values())

            # --- Score against manifest ---
            manifest_count, detected_in_manifest, recall, precision, f1 = (
                await self._score_against_manifest(tenant_id)
            )

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
                        cmdb_entity_count, gt_entity_count, confirmed_entity_count,
                        cmdb_edge_count, gt_edge_count, confirmed_edge_count,
                        manifest_count, detected_in_manifest,
                        recall_score, precision_score, f1_score,
                        started_at, completed_at
                    ) VALUES (
                        :run_id, :tid, 'manual', 'complete',
                        :total, :dark_nodes, :phantom_nodes,
                        :identity_mutations, :dark_attributes, :dark_edges, :phantom_edges,
                        :cmdb_count, :gt_count, :confirmed_count,
                        :cmdb_edges, :gt_edges, :confirmed_edges,
                        :manifest_count, :detected_in_manifest,
                        :recall, :precision, :f1,
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
                    "cmdb_count": str(cmdb_count),
                    "gt_count": str(gt_count),
                    "confirmed_count": str(confirmed_count),
                    "cmdb_edges": str(cmdb_edge_count),
                    "gt_edges": str(gt_edge_count),
                    "confirmed_edges": str(confirmed_edge_count),
                    "manifest_count": str(manifest_count),
                    "detected_in_manifest": str(detected_in_manifest),
                    "recall": recall,
                    "precision": precision,
                    "f1": f1,
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
            await self.session.commit()

            logger.info(
                f"[Reconciliation] Run {self.run_id} complete: "
                f"{total:,} divergences in {duration_s:.1f}s | "
                f"Recall={recall:.3f} Precision={precision:.3f} F1={f1:.3f}"
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
                "cmdb_stats": {
                    "entity_count": cmdb_count,
                    "entity_accuracy": round(confirmed_count / max(gt_count, 1), 4),
                    "edge_count": cmdb_edge_count,
                    "edge_accuracy": round(confirmed_edge_count / max(gt_edge_count, 1), 4),
                },
                "ground_truth_stats": {
                    "entity_count": gt_count,
                    "edge_count": gt_edge_count,
                },
                "scoring": {
                    "manifest_count": manifest_count,
                    "detected_in_manifest": detected_in_manifest,
                    "recall": round(recall, 4),
                    "precision": round(precision, 4),
                    "f1": round(f1, 4),
                },
            }

        except Exception as exc:
            logger.error(f"[Reconciliation] Run {self.run_id} failed: {exc}", exc_info=True)
            await self.session.rollback()
            raise

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    async def _detect_dark_nodes(self) -> int:
        """GT entities with no matching CMDB entity → dark nodes."""
        logger.info("[Reconciliation] Detecting dark nodes…")
        rows = await self._fetch(
            """
            SELECT
                gt.entity_id   AS target_id,
                gt.entity_type AS target_type,
                gt.domain      AS domain,
                gt.name        AS name
            FROM gt_network_entities gt
            WHERE gt.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM network_entities ne
                  WHERE CAST(ne.id AS TEXT) = gt.entity_id
                    AND ne.tenant_id = gt.tenant_id
              )
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(self.tenant_id, "dark_node", r["target_id"]),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "dark_node",
                "entity_or_relationship": "entity",
                "target_id": r["target_id"],
                "target_type": r["target_type"],
                "domain": r["domain"],
                "description": (
                    f"Entity {r['name']} ({r['target_type']}) exists in ground truth "
                    f"but is missing from CMDB. Domain: {r['domain']}."
                ),
                "confidence": 1.0,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  → {len(records):,} dark nodes")
        return len(records)

    async def _detect_phantom_nodes(self) -> int:
        """CMDB entities with no matching GT entity → phantom nodes."""
        logger.info("[Reconciliation] Detecting phantom nodes…")
        rows = await self._fetch(
            """
            SELECT
                CAST(ne.id AS TEXT)    AS target_id,
                ne.entity_type AS target_type,
                ne.name        AS name,
                ne.attributes->>'domain' AS domain
            FROM network_entities ne
            WHERE ne.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM gt_network_entities gt
                  WHERE gt.entity_id = CAST(ne.id AS TEXT)
                    AND gt.tenant_id = ne.tenant_id
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
                    f"CMDB entity {r['name']} ({r['target_type']}) has no ground truth "
                    f"telemetry presence. May be decommissioned or a phantom CI."
                ),
                "confidence": 1.0,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  → {len(records):,} phantom nodes")
        return len(records)

    async def _detect_identity_mutations(self) -> int:
        """Both tables have the entity, but external_id has drifted → identity mutation."""
        logger.info("[Reconciliation] Detecting identity mutations…")
        rows = await self._fetch(
            """
            SELECT
                CAST(ne.id AS TEXT)    AS target_id,
                ne.entity_type AS target_type,
                ne.name        AS name,
                ne.external_id AS cmdb_external_id,
                gt.external_id AS gt_external_id,
                gt.domain      AS domain
            FROM network_entities ne
            JOIN gt_network_entities gt
              ON gt.entity_id = CAST(ne.id AS TEXT) AND gt.tenant_id = ne.tenant_id
            WHERE ne.tenant_id = :tid
              AND ne.external_id IS DISTINCT FROM gt.external_id
              AND ne.external_id IS NOT NULL
              AND gt.external_id IS NOT NULL
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(self.tenant_id, "identity_mutation", r["target_id"]),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "identity_mutation",
                "entity_or_relationship": "entity",
                "target_id": r["target_id"],
                "target_type": r["target_type"],
                "domain": r["domain"],
                "description": (
                    f"External ID drift detected for {r['name']} ({r['target_type']}). "
                    f"CMDB: '{r['cmdb_external_id']}' → Reality: '{r['gt_external_id']}'. "
                    f"Likely CMDB entry error or hardware swap without CMDB update."
                ),
                "cmdb_external_id": r["cmdb_external_id"],
                "gt_external_id": r["gt_external_id"],
                "confidence": 0.9,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  → {len(records):,} identity mutations")
        return len(records)

    async def _detect_dark_attributes(self) -> int:
        """Entities present in both tables but with attribute value mismatches."""
        logger.info("[Reconciliation] Detecting dark attributes…")
        all_records: list[dict] = []

        for attr in COMPARABLE_ATTRIBUTES:
            rows = await self._fetch(
                f"""
                SELECT
                    CAST(ne.id AS TEXT)         AS target_id,
                    ne.entity_type      AS target_type,
                    ne.name             AS name,
                    gt.domain           AS domain,
                    ne.attributes->>'{attr}' AS cmdb_val,
                    gt.attributes->>'{attr}' AS gt_val
                FROM network_entities ne
                JOIN gt_network_entities gt
                  ON gt.entity_id = CAST(ne.id AS TEXT) AND gt.tenant_id = ne.tenant_id
                WHERE ne.tenant_id = :tid
                  AND ne.attributes->>'{attr}' IS DISTINCT FROM gt.attributes->>'{attr}'
                  AND ne.attributes->>'{attr}' IS NOT NULL
                  AND gt.attributes->>'{attr}' IS NOT NULL
                """,  # nosec — attr is from a hardcoded list
                {"tid": self.tenant_id},
            )
            for r in rows:
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
                            f"Attribute '{attr}' stale/incorrect in CMDB for {r['name']} "
                            f"({r['target_type']}). "
                            f"CMDB='{r['cmdb_val']}' vs Reality='{r['gt_val']}'."
                        ),
                        "attribute_name": attr,
                        "cmdb_value": r["cmdb_val"],
                        "ground_truth_value": r["gt_val"],
                        "confidence": 0.95,
                    }
                )

        await self._bulk_insert(all_records)
        logger.info(f"  → {len(all_records):,} dark attributes")
        return len(all_records)

    async def _detect_dark_edges(self) -> int:
        """GT edges with no matching CMDB edge → dark edges (undocumented dependencies)."""
        logger.info("[Reconciliation] Detecting dark edges…")
        rows = await self._fetch(
            """
            SELECT
                gt.relationship_id                AS target_id,
                gt.relationship_type              AS rel_type,
                gt.from_entity_id                 AS from_id,
                gt.from_entity_type               AS from_type,
                gt.to_entity_id                   AS to_id,
                gt.to_entity_type                 AS to_type,
                gt.domain                         AS domain
            FROM gt_entity_relationships gt
            WHERE gt.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM topology_relationships tr
                  WHERE tr.from_entity_id = gt.from_entity_id
                    AND tr.to_entity_id   = gt.to_entity_id
                    AND tr.relationship_type = gt.relationship_type
                    AND tr.tenant_id = gt.tenant_id
              )
            """,
            {"tid": self.tenant_id},
        )
        records = [
            {
                "result_id": _make_result_id(
                    self.tenant_id, "dark_edge",
                    r["from_id"], r["to_id"], r["rel_type"]
                ),
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "divergence_type": "dark_edge",
                "entity_or_relationship": "relationship",
                "target_id": r["target_id"],
                "target_type": r["rel_type"],
                "domain": r["domain"],
                "description": (
                    f"Undocumented dependency: {r['from_type']} → {r['to_type']} "
                    f"({r['rel_type']}) exists in ground truth but not in CMDB."
                ),
                "confidence": 1.0,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  → {len(records):,} dark edges")
        return len(records)

    async def _detect_phantom_edges(self) -> int:
        """CMDB edges with no matching GT edge → phantom edges (stale declared relationships)."""
        logger.info("[Reconciliation] Detecting phantom edges…")
        rows = await self._fetch(
            """
            SELECT
                CAST(tr.id AS TEXT)  AS target_id,
                tr.relationship_type AS rel_type,
                tr.from_entity_id  AS from_id,
                tr.from_entity_type AS from_type,
                tr.to_entity_id    AS to_id,
                tr.to_entity_type  AS to_type
            FROM topology_relationships tr
            WHERE tr.tenant_id = :tid
              AND NOT EXISTS (
                  SELECT 1 FROM gt_entity_relationships gt
                  WHERE gt.from_entity_id   = tr.from_entity_id
                    AND gt.to_entity_id     = tr.to_entity_id
                    AND gt.relationship_type = tr.relationship_type
                    AND gt.tenant_id = tr.tenant_id
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
                    f"Stale CMDB dependency: {r['from_type']} → {r['to_type']} "
                    f"({r['rel_type']}) is declared in CMDB but has no reality counterpart."
                ),
                "confidence": 1.0,
            }
            for r in rows
        ]
        await self._bulk_insert(records)
        logger.info(f"  → {len(records):,} phantom edges")
        return len(records)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def _score_against_manifest(
        self, tenant_id: str
    ) -> tuple[int, int, float, float, float]:
        """
        Compare discovered divergences against pre-seeded divergence_manifest.

        Returns: (manifest_count, detected_in_manifest, recall, precision, f1)

        Note: divergence_manifest target_ids map to our result target_ids.
        We use target_id + divergence_type as the match key.
        """
        manifest_count = await self._scalar(
            "SELECT COUNT(*) FROM divergence_manifest WHERE tenant_id = :tid",
            {"tid": tenant_id},
        )
        if manifest_count == 0:
            return 0, 0, 0.0, 0.0, 0.0

        # How many manifest entries did the engine detect?
        detected_in_manifest = await self._scalar(
            """
            SELECT COUNT(*)
            FROM divergence_manifest dm
            WHERE dm.tenant_id = :tid
              AND EXISTS (
                  SELECT 1 FROM reconciliation_results rr
                  WHERE rr.tenant_id = :tid
                    AND rr.target_id = dm.target_id
                    AND rr.divergence_type = dm.divergence_type
              )
            """,
            {"tid": tenant_id},
        )

        total_detected = await self._scalar(
            "SELECT COUNT(*) FROM reconciliation_results WHERE tenant_id = :tid AND run_id = :rid",
            {"tid": tenant_id, "rid": self.run_id},
        )

        recall = detected_in_manifest / max(manifest_count, 1)
        precision = detected_in_manifest / max(total_detected, 1)
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return manifest_count, detected_in_manifest, recall, precision, f1

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
                        description, attribute_name, cmdb_value, ground_truth_value,
                        cmdb_external_id, gt_external_id, confidence
                    ) VALUES (
                        :result_id, :tenant_id, :run_id, :divergence_type,
                        :entity_or_relationship, :target_id, :target_type, :domain,
                        :description, :attribute_name, :cmdb_value, :ground_truth_value,
                        :cmdb_external_id, :gt_external_id, :confidence
                    )
                    ON CONFLICT (result_id) DO NOTHING
                    """
                ),
                [
                    {
                        "attribute_name": r.get("attribute_name"),
                        "cmdb_value": r.get("cmdb_value"),
                        "ground_truth_value": r.get("ground_truth_value"),
                        "cmdb_external_id": r.get("cmdb_external_id"),
                        "gt_external_id": r.get("gt_external_id"),
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
        """Create reconciliation tables if they don't exist yet."""
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
                    gt_entity_count TEXT DEFAULT '0',
                    confirmed_entity_count TEXT DEFAULT '0',
                    cmdb_edge_count TEXT DEFAULT '0',
                    gt_edge_count TEXT DEFAULT '0',
                    confirmed_edge_count TEXT DEFAULT '0',
                    manifest_count TEXT DEFAULT '0',
                    detected_in_manifest TEXT DEFAULT '0',
                    recall_score FLOAT,
                    precision_score FLOAT,
                    f1_score FLOAT,
                    error_message TEXT,
                    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMPTZ
                )
                """
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
                    ground_truth_value TEXT,
                    cmdb_external_id TEXT,
                    gt_external_id TEXT,
                    confidence FLOAT DEFAULT 1.0,
                    extra JSONB,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
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
