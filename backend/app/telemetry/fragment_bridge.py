"""
Telemetry → Abeyance Memory Fragment Bridge.

Converts streaming telemetry events (alarms and KPI anomalies) into
Abeyance Memory fragments, feeding the enrichment chain, snap engine,
accumulation graph, and all 14 discovery mechanisms.

This is the missing link between Layer 1 (Data Fabric) and Layer 2
(Living Context Graph) in the PedkAI architecture.

LLD v3 ref:
    §4 — Architecture: Telemetry Streams → Enrichment Chain → Fragment Store
    §5 — Fragment Model: ALARM (τ=90d) and TELEMETRY_EVENT (τ=60d) source types
    §6 — Enrichment Chain: Entity resolution → fingerprinting → classification → embedding

Design:
    - Decoupled from the Kafka consumer's write path (non-blocking queue)
    - Alarms: every alarm is evidence (queued immediately)
    - KPI anomalies: lightweight z-score detection, only outliers become fragments
    - Background worker processes queue through the enrichment chain
    - Works with v3 (T-VEC + TSLAM)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from typing import Any

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Alarm → natural language template (Face 1: "What it says")
# ---------------------------------------------------------------------------
_ALARM_TEMPLATE = (
    "{severity} alarm on entity {entity_id} ({entity_type}, {domain}): "
    "{alarm_type}. "
    "Raised at {raised_at}. "
    "{probable_cause_text}"
    "{additional_text}"
    "Source system: {source_system}."
)

# ---------------------------------------------------------------------------
# KPI Anomaly → natural language template (reuses TelemetryAligner pattern)
# ---------------------------------------------------------------------------
_ANOMALY_TEMPLATE = (
    "KPI anomaly on entity {entity_id} ({domain}): {kpi_name} = {value:.4f} "
    "({z_score:.1f} standard deviations from baseline). "
    "Timestamp: {timestamp}."
)


# ---------------------------------------------------------------------------
# Lightweight rolling z-score tracker (Welford's online algorithm)
# ---------------------------------------------------------------------------

class _WelfordAccumulator:
    """Online mean/variance tracker using Welford's algorithm.

    Memory-efficient: O(1) per (entity_id, kpi_name) pair.
    Numerically stable for large streams.
    """

    __slots__ = ("n", "mean", "m2")

    def __init__(self):
        self.n: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0

    def update(self, value: float) -> float | None:
        """Add a value and return the z-score (None if < 10 observations)."""
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        delta2 = value - self.mean
        self.m2 += delta * delta2

        if self.n < 10:
            return None  # Insufficient data for baseline

        variance = self.m2 / self.n
        stddev = sqrt(variance) if variance > 0 else 0.0
        if stddev < 1e-10:
            return 0.0
        return (value - self.mean) / stddev


class AnomalyDetector:
    """
    Lightweight per-entity per-KPI anomaly detector.

    Uses Welford's online algorithm to maintain rolling statistics
    with O(1) memory per tracked key. Reports z-scores exceeding
    the configured threshold.

    Does NOT replace a proper anomaly detection engine — this is a
    first-pass filter to identify fragment candidates from raw KPI data.
    """

    def __init__(self, z_threshold: float = 3.0, max_tracked: int = 500_000):
        self.z_threshold = z_threshold
        self.max_tracked = max_tracked
        self._accumulators: dict[tuple[str, str], _WelfordAccumulator] = {}

    def check(
        self, entity_id: str, kpi_name: str, value: float
    ) -> float | None:
        """
        Update statistics and return z-score if it exceeds threshold.

        Returns None if:
        - Value is within normal range
        - Insufficient baseline observations (< 10)
        - Max tracked keys exceeded (drops new keys)
        """
        key = (entity_id, kpi_name)
        acc = self._accumulators.get(key)
        if acc is None:
            if len(self._accumulators) >= self.max_tracked:
                return None  # Bounded memory
            acc = _WelfordAccumulator()
            self._accumulators[key] = acc

        z = acc.update(value)
        if z is not None and abs(z) >= self.z_threshold:
            return z
        return None


# ---------------------------------------------------------------------------
# Fragment Bridge
# ---------------------------------------------------------------------------

class TelemetryFragmentBridge:
    """
    Bridges streaming telemetry into Abeyance Memory fragment ingestion.

    Operates as a background asyncio worker:
    1. Kafka consumer enqueues alarm/anomaly events (non-blocking)
    2. Worker dequeues in batches
    3. Converts to natural language evidence (Face 1)
    4. Runs through enrichment chain → snap engine → accumulation graph
    5. Fragments stored in graph DB alongside existing abeyance data

    The consumer's production write path (kpi_metrics, telco_events_alarms)
    is completely unaffected — this is a parallel best-effort pipeline.
    """

    def __init__(
        self,
        queue_size: int = 10_000,
        batch_size: int = 50,
        flush_interval: float = 10.0,
    ):
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(
            maxsize=queue_size
        )
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._running = False
        self._services: dict | None = None

        # Stats
        self._enqueued = 0
        self._dropped = 0
        self._processed = 0
        self._errors = 0

    # -- Public interface (called from Kafka consumer) --------------------

    def enqueue_alarm(self, alarm: dict[str, Any]) -> None:
        """Non-blocking enqueue of an alarm event. Drops silently if full."""
        try:
            self._queue.put_nowait(("ALARM", alarm))
            self._enqueued += 1
        except asyncio.QueueFull:
            self._dropped += 1

    def enqueue_anomaly(
        self,
        entity_id: str,
        kpi_name: str,
        value: float,
        z_score: float,
        domain: str,
        tenant_id: str,
        timestamp: datetime,
    ) -> None:
        """Non-blocking enqueue of a KPI anomaly. Drops silently if full."""
        event = {
            "entity_id": entity_id,
            "kpi_name": kpi_name,
            "value": value,
            "z_score": z_score,
            "domain": domain,
            "tenant_id": tenant_id,
            "timestamp": timestamp,
        }
        try:
            self._queue.put_nowait(("TELEMETRY_EVENT", event))
            self._enqueued += 1
        except asyncio.QueueFull:
            self._dropped += 1

    # -- Background worker ------------------------------------------------

    async def run(self) -> None:
        """
        Main processing loop. Dequeues events and feeds them through
        the Abeyance Memory enrichment chain.
        """
        from backend.app.services.abeyance import create_abeyance_services

        self._services = create_abeyance_services()
        self._running = True

        logger.info(
            "Fragment bridge started (queue_size=%d, batch_size=%d)",
            self._queue.maxsize,
            self._batch_size,
        )

        while self._running:
            batch = await self._collect_batch()
            if not batch:
                continue

            await self._process_batch(batch)

            # Periodic stats
            if self._processed % 100 < self._batch_size:
                logger.info(
                    "Fragment bridge: enqueued=%d, processed=%d, errors=%d, dropped=%d, pending=%d",
                    self._enqueued,
                    self._processed,
                    self._errors,
                    self._dropped,
                    self._queue.qsize(),
                )

    async def stop(self) -> None:
        """Signal stop and drain remaining queue."""
        self._running = False
        # Drain what's left
        while not self._queue.empty():
            batch = await self._collect_batch()
            if batch:
                await self._process_batch(batch)

        logger.info(
            "Fragment bridge stopped. Processed=%d, Errors=%d, Dropped=%d",
            self._processed,
            self._errors,
            self._dropped,
        )

    async def _collect_batch(self) -> list[tuple[str, dict[str, Any]]]:
        """Collect up to batch_size items, waiting up to flush_interval."""
        batch: list[tuple[str, dict[str, Any]]] = []

        # Block on first item (with timeout)
        try:
            item = await asyncio.wait_for(
                self._queue.get(), timeout=self._flush_interval
            )
            batch.append(item)
        except asyncio.TimeoutError:
            return batch

        # Drain up to batch_size without blocking
        while len(batch) < self._batch_size:
            try:
                item = self._queue.get_nowait()
                batch.append(item)
            except asyncio.QueueEmpty:
                break

        return batch

    async def _process_batch(
        self, batch: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Process a batch of events through the enrichment chain."""
        from backend.app.core.database import get_db_context

        enrichment = self._services["enrichment_v3"]
        snap_engine = self._services["snap_engine_v3"]
        accumulation = self._services["accumulation_graph"]

        for source_type, event in batch:
            try:
                async with get_db_context() as session:
                    # Convert event to enrichment-chain inputs
                    if source_type == "ALARM":
                        raw_content, tenant_id, event_ts, source_ref, entity_refs = (
                            self._alarm_to_evidence(event)
                        )
                    elif source_type == "TELEMETRY_EVENT":
                        raw_content, tenant_id, event_ts, source_ref, entity_refs = (
                            self._anomaly_to_evidence(event)
                        )
                    else:
                        continue

                    if not raw_content or not tenant_id:
                        continue

                    # Stage 1: Enrichment Chain (LLD §6)
                    fragment = await enrichment.enrich(
                        session=session,
                        tenant_id=tenant_id,
                        raw_content=raw_content,
                        source_type=source_type,
                        event_timestamp=event_ts,
                        source_ref=source_ref,
                        explicit_entity_refs=entity_refs,
                        metadata=event,
                    )
                    await session.flush()

                    # Stage 2: Snap Engine evaluation (LLD §9)
                    try:
                        await snap_engine.evaluate(
                            session=session,
                            new_fragment=fragment,
                            tenant_id=tenant_id,
                        )
                    except Exception as e:
                        logger.debug("Snap evaluation error: %s", e)

                    # Stage 3: Accumulation graph (LLD §10)
                    try:
                        await accumulation.detect_and_evaluate_clusters(
                            session=session,
                            tenant_id=tenant_id,
                            trigger_fragment_id=fragment.id,
                        )
                    except Exception as e:
                        logger.debug("Cluster detection error: %s", e)

                    # Stage 4: Create incident from newly-snapped clusters
                    try:
                        await self._create_incident_from_snaps(
                            session, tenant_id
                        )
                    except Exception as e:
                        logger.debug("Incident creation error: %s", e)

                    await session.commit()
                    self._processed += 1

            except Exception as e:
                logger.error("Fragment bridge error (%s): %s", source_type, e)
                self._errors += 1

    # -- Stage 4: Incident creation from snapped clusters -------------------

    async def _create_incident_from_snaps(
        self, session: Any, tenant_id: str
    ) -> None:
        """
        Check for newly-snapped fragments and create incidents.

        When the accumulation graph detects a cluster snap (score >= 0.70),
        fragments are marked SNAPPED with a shared snapped_hypothesis_id.
        This method finds hypothesis groups that don't yet have an incident
        and creates one in ANOMALY status (the proto-incident).

        Then attempts to auto-generate a SITREP via Ollama for human review.
        """
        from sqlalchemy import func, select

        from backend.app.models.abeyance_orm import AbeyanceFragmentORM
        from backend.app.models.incident_orm import IncidentORM

        # Find hypothesis IDs with SNAPPED fragments
        hyp_query = (
            select(AbeyanceFragmentORM.snapped_hypothesis_id)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.snap_status == "SNAPPED",
                AbeyanceFragmentORM.snapped_hypothesis_id.isnot(None),
            )
            .group_by(AbeyanceFragmentORM.snapped_hypothesis_id)
        )
        result = await session.execute(hyp_query)
        hypothesis_ids = [row[0] for row in result.fetchall()]

        if not hypothesis_ids:
            return

        for hyp_id in hypothesis_ids:
            # Check if an incident already exists for this hypothesis
            existing = await session.execute(
                select(func.count()).select_from(IncidentORM).where(
                    IncidentORM.tenant_id == tenant_id,
                    IncidentORM.title.contains(str(hyp_id)[:8]),
                )
            )
            if (existing.scalar() or 0) > 0:
                continue  # Already created

            # Gather all fragments in this hypothesis cluster
            frags = await session.execute(
                select(AbeyanceFragmentORM).where(
                    AbeyanceFragmentORM.snapped_hypothesis_id == hyp_id,
                    AbeyanceFragmentORM.tenant_id == tenant_id,
                )
            )
            fragments = frags.scalars().all()
            if not fragments:
                continue

            # Build incident from fragment evidence
            title, severity, entity_id, reasoning_chain = (
                self._synthesize_incident_from_fragments(fragments, hyp_id)
            )

            # Create incident via service
            try:
                from backend.app.schemas.incidents import IncidentCreate
                from backend.app.services.incident_service import (
                    create_incident_from_cluster,
                )

                payload = IncidentCreate(
                    tenant_id=tenant_id,
                    title=title,
                    severity=severity,
                    entity_id=entity_id,
                )
                incident = await create_incident_from_cluster(
                    payload, session, tenant_id
                )
                # Store reasoning chain
                incident.reasoning_chain = reasoning_chain

                logger.info(
                    "Incident created from AM cluster snap: id=%s hyp=%s "
                    "fragments=%d severity=%s",
                    incident.id, str(hyp_id)[:8],
                    len(fragments), severity,
                )

                # Attempt SITREP generation via LLM (best-effort)
                await self._generate_sitrep_for_incident(
                    session, incident, fragments, tenant_id
                )

            except Exception as e:
                logger.error(
                    "Failed to create incident from hypothesis %s: %s",
                    str(hyp_id)[:8], e,
                )

    @staticmethod
    def _synthesize_incident_from_fragments(
        fragments: list, hyp_id: Any
    ) -> tuple[str, str, str | None, list[dict]]:
        """
        Synthesize incident title, severity, entity, and reasoning chain
        from a cluster of snapped fragments.
        """
        # Collect entity refs and failure modes across all fragments
        all_entities: list[str] = []
        all_failure_modes: list[str] = []
        severities: list[str] = []
        reasoning_chain: list[dict] = []

        for frag in fragments:
            # Gather entity references
            if frag.extracted_entities:
                for ent in frag.extracted_entities:
                    if isinstance(ent, dict):
                        all_entities.append(ent.get("identifier", "unknown"))
                    elif isinstance(ent, str):
                        all_entities.append(ent)

            # Gather failure modes
            if frag.failure_mode_tags:
                for tag in frag.failure_mode_tags:
                    if isinstance(tag, str):
                        all_failure_modes.append(tag)

            # Parse severity from raw_content
            raw = (frag.raw_content or "").lower()
            if "critical" in raw:
                severities.append("critical")
            elif "major" in raw:
                severities.append("major")
            elif "minor" in raw:
                severities.append("minor")

            # Build reasoning step per fragment
            reasoning_chain.append({
                "step": f"Fragment {frag.source_type}",
                "fragment_id": str(frag.id),
                "timestamp": frag.event_timestamp.isoformat() if frag.event_timestamp else None,
                "detail": (frag.raw_content or "")[:200],
                "entities": all_entities[-3:] if all_entities else [],
            })

        # Determine primary entity (most frequently referenced)
        entity_id = None
        if all_entities:
            from collections import Counter
            entity_counts = Counter(all_entities)
            entity_id = entity_counts.most_common(1)[0][0]

        # Determine severity (highest in cluster)
        severity_order = {"critical": 0, "major": 1, "minor": 2}
        if severities:
            severities.sort(key=lambda s: severity_order.get(s, 99))
            severity = severities[0]
        else:
            severity = "major"

        # Determine dominant failure modes
        unique_modes = list(dict.fromkeys(all_failure_modes))[:3]
        mode_text = ", ".join(unique_modes) if unique_modes else "correlated anomalies"

        # Unique entities for title
        unique_entities = list(dict.fromkeys(all_entities))[:3]
        entity_text = ", ".join(unique_entities) if unique_entities else "multiple entities"

        title = (
            f"[AM] {mode_text} affecting {entity_text} "
            f"({len(fragments)} fragments, hyp:{str(hyp_id)[:8]})"
        )

        # Add cluster-level reasoning step
        reasoning_chain.append({
            "step": "Cluster snap",
            "hypothesis_id": str(hyp_id),
            "fragment_count": len(fragments),
            "failure_modes": unique_modes,
            "entities": unique_entities,
        })

        return title, severity, entity_id, reasoning_chain

    @staticmethod
    async def _generate_sitrep_for_incident(
        session: Any, incident: Any, fragments: list, tenant_id: str
    ) -> None:
        """
        Auto-generate SITREP via LLM (Ollama) and advance to SITREP_DRAFT.
        Best-effort — if LLM is unavailable, incident stays in ANOMALY status.
        """
        try:
            from backend.app.services.llm_service import generate_sitrep

            # Build incident context for SITREP generation
            entity_refs = []
            for frag in fragments:
                if frag.extracted_entities:
                    for ent in frag.extracted_entities:
                        if isinstance(ent, dict):
                            entity_refs.append(ent.get("identifier", ""))
                        elif isinstance(ent, str):
                            entity_refs.append(ent)

            incident_context = {
                "entity_id": incident.entity_id or "unknown",
                "entity_name": incident.entity_id or "unknown",
                "severity": incident.severity,
                "title": incident.title,
                "fragment_count": len(fragments),
                "failure_modes": [
                    tag for frag in fragments
                    if frag.failure_mode_tags
                    for tag in frag.failure_mode_tags
                    if isinstance(tag, str)
                ][:5],
                "affected_entities": list(dict.fromkeys(entity_refs))[:10],
            }

            sitrep = await generate_sitrep(
                incident_context=incident_context,
                similar_decisions=[],
                session=session,
            )

            if sitrep and sitrep.get("text"):
                incident.resolution_summary = sitrep["text"]
                incident.llm_model_version = sitrep.get("model_version")
                incident.llm_prompt_hash = sitrep.get("prompt_hash")
                incident.status = "sitrep_draft"
                logger.info(
                    "SITREP generated for incident %s (confidence=%.2f)",
                    incident.id,
                    sitrep.get("confidence", 0),
                )

        except Exception as e:
            # LLM unavailable — incident stays in ANOMALY status
            logger.debug("SITREP generation skipped for %s: %s", incident.id, e)

    # -- Event → evidence converters --------------------------------------

    @staticmethod
    def _alarm_to_evidence(
        alarm: dict[str, Any],
    ) -> tuple[str, str, datetime | None, str | None, list[str]]:
        """
        Convert an alarm dict to enrichment-chain inputs.

        Returns: (raw_content, tenant_id, event_timestamp, source_ref, entity_refs)
        """
        tenant_id = alarm.get("tenant_id", "")
        entity_id = str(alarm.get("entity_id", ""))
        alarm_id = alarm.get("alarm_id")
        severity = alarm.get("severity", "unknown")
        alarm_type = alarm.get("alarm_type", "unknown")
        domain = alarm.get("domain", "unknown")
        entity_type = alarm.get("entity_type", "unknown")
        source_system = alarm.get("source_system", "unknown")
        probable_cause = alarm.get("probable_cause")
        additional_text = alarm.get("additional_text")
        raised_at = alarm.get("raised_at")

        # Format timestamp
        if isinstance(raised_at, str):
            raised_at_str = raised_at
            raised_at_dt = datetime.fromisoformat(raised_at)
        elif isinstance(raised_at, datetime):
            raised_at_str = raised_at.isoformat()
            raised_at_dt = raised_at
        else:
            raised_at_str = "unknown"
            raised_at_dt = None

        raw_content = _ALARM_TEMPLATE.format(
            severity=severity.upper(),
            entity_id=entity_id,
            entity_type=entity_type or "unknown",
            domain=domain,
            alarm_type=alarm_type,
            raised_at=raised_at_str,
            probable_cause_text=(
                f"Probable cause: {probable_cause}. " if probable_cause else ""
            ),
            additional_text=(
                f"{additional_text}. " if additional_text else ""
            ),
            source_system=source_system,
        )

        entity_refs = [entity_id] if entity_id else []

        return raw_content, tenant_id, raised_at_dt, str(alarm_id), entity_refs

    @staticmethod
    def _anomaly_to_evidence(
        event: dict[str, Any],
    ) -> tuple[str, str, datetime | None, str | None, list[str]]:
        """
        Convert a KPI anomaly dict to enrichment-chain inputs.

        Returns: (raw_content, tenant_id, event_timestamp, source_ref, entity_refs)
        """
        entity_id = str(event.get("entity_id", ""))
        tenant_id = event.get("tenant_id", "")
        kpi_name = event.get("kpi_name", "unknown")
        value = event.get("value", 0.0)
        z_score = event.get("z_score", 0.0)
        domain = event.get("domain", "unknown")
        timestamp = event.get("timestamp")

        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        ts_str = (
            timestamp.strftime("%Y-%m-%d %H:%M UTC")
            if isinstance(timestamp, datetime)
            else "unknown"
        )

        raw_content = _ANOMALY_TEMPLATE.format(
            entity_id=entity_id,
            domain=domain,
            kpi_name=kpi_name,
            value=value,
            z_score=z_score,
            timestamp=ts_str,
        )

        source_ref = f"anomaly:{entity_id}:{kpi_name}:{ts_str}"
        entity_refs = [entity_id] if entity_id else []

        return raw_content, tenant_id, timestamp, source_ref, entity_refs


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

async def start_fragment_bridge() -> tuple[TelemetryFragmentBridge, asyncio.Task]:
    """
    Start the fragment bridge as a background asyncio task.

    Returns (bridge_instance, task) so the consumer can call bridge.enqueue_*()
    and the lifespan can cancel the task on shutdown.
    """
    bridge = TelemetryFragmentBridge(
        queue_size=getattr(settings, "abeyance_fragment_queue_size", 10_000),
        batch_size=50,
        flush_interval=10.0,
    )

    async def _run():
        try:
            await bridge.run()
        except asyncio.CancelledError:
            await bridge.stop()
        except Exception as e:
            logger.error("Fragment bridge crashed: %s", e, exc_info=True)
            await bridge.stop()

    task = asyncio.create_task(_run(), name="fragment-bridge")
    logger.info("Telemetry → Abeyance Memory fragment bridge started")
    return bridge, task
