"""
Discovery Loop — end-to-end event processing orchestrator (LLD v3.0 §12).

Six stages: Ingest → Enrich → Score → Detect → Generate → Learn.
Wires all 14 discovery mechanisms through the five-layer cognitive architecture.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import AbeyanceFragmentORM
from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
from backend.app.services.abeyance.snap_engine_v3 import SnapEngineV3
from backend.app.services.abeyance.accumulation_graph import AccumulationGraph
from backend.app.services.abeyance.decay_engine import DecayEngine
from backend.app.services.abeyance.events import ProvenanceLogger, RedisNotifier

# Layer 2
from backend.app.services.abeyance.discovery.surprise_engine import SurpriseEngine
from backend.app.services.abeyance.discovery.ignorance_mapper import IgnoranceMapper
from backend.app.services.abeyance.discovery.negative_evidence import NegativeEvidenceService
from backend.app.services.abeyance.discovery.bridge_detector import BridgeDetector
from backend.app.services.abeyance.discovery.outcome_calibration import OutcomeCalibrationService
from backend.app.services.abeyance.discovery.pattern_conflict import PatternConflictDetector
from backend.app.services.abeyance.discovery.temporal_sequence import TemporalSequenceModeller

# Layer 3
from backend.app.services.abeyance.discovery.hypothesis_generator import HypothesisGenerator
from backend.app.services.abeyance.discovery.expectation_violation import ExpectationViolationDetector
from backend.app.services.abeyance.discovery.causal_direction import CausalDirectionTester

# Layer 4
from backend.app.services.abeyance.discovery.pattern_compression import PatternCompressor
from backend.app.services.abeyance.discovery.counterfactual_sim import CounterfactualSimulator

# Layer 5
from backend.app.services.abeyance.discovery.meta_memory import MetaMemoryService
from backend.app.services.abeyance.discovery.evolutionary_patterns import EvolutionaryPatternService

logger = logging.getLogger(__name__)


class DiscoveryLoop:
    """End-to-end discovery loop orchestrator.

    Startup order (LLD §11.4):
    1. Layer 1 services (enrichment, snap, decay)
    2. Layer 2 discovery mechanisms
    3. Layer 3 hypothesis mechanisms
    4. Layer 4 evidence mechanisms
    5. Layer 5 insight mechanisms
    6. Wire feedback loops (A: calibration→snap, B: meta→enrichment)
    """

    def __init__(
        self,
        # Layer 1
        enrichment: EnrichmentChainV3,
        snap_engine: SnapEngineV3,
        accumulation_graph: AccumulationGraph,
        decay_engine: DecayEngine,
        provenance: ProvenanceLogger,
        notifier: RedisNotifier,
        # Layer 2
        surprise_engine: Optional[SurpriseEngine] = None,
        ignorance_mapper: Optional[IgnoranceMapper] = None,
        negative_evidence: Optional[NegativeEvidenceService] = None,
        bridge_detector: Optional[BridgeDetector] = None,
        outcome_calibration: Optional[OutcomeCalibrationService] = None,
        pattern_conflict: Optional[PatternConflictDetector] = None,
        temporal_sequence: Optional[TemporalSequenceModeller] = None,
        # Layer 3
        hypothesis_generator: Optional[HypothesisGenerator] = None,
        expectation_violation: Optional[ExpectationViolationDetector] = None,
        causal_direction: Optional[CausalDirectionTester] = None,
        # Layer 4
        pattern_compressor: Optional[PatternCompressor] = None,
        counterfactual_sim: Optional[CounterfactualSimulator] = None,
        # Layer 5
        meta_memory: Optional[MetaMemoryService] = None,
        evolutionary_patterns: Optional[EvolutionaryPatternService] = None,
    ):
        # Layer 1
        self._enrichment = enrichment
        self._snap = snap_engine
        self._accumulation = accumulation_graph
        self._decay = decay_engine
        self._provenance = provenance
        self._notifier = notifier

        # Layer 2
        self._surprise = surprise_engine or SurpriseEngine()
        self._ignorance = ignorance_mapper or IgnoranceMapper()
        self._negative_evidence = negative_evidence
        self._bridge = bridge_detector or BridgeDetector()
        self._calibration = outcome_calibration or OutcomeCalibrationService()
        self._conflict = pattern_conflict or PatternConflictDetector()
        self._temporal = temporal_sequence or TemporalSequenceModeller()

        # Layer 3
        self._hypothesis = hypothesis_generator or HypothesisGenerator()
        self._violation = expectation_violation or ExpectationViolationDetector(self._temporal)
        self._causal = causal_direction or CausalDirectionTester()

        # Layer 4
        self._compressor = pattern_compressor or PatternCompressor()
        self._counterfactual = counterfactual_sim or CounterfactualSimulator(self._snap)

        # Layer 5
        self._meta_memory = meta_memory or MetaMemoryService()
        self._evolution = evolutionary_patterns or EvolutionaryPatternService()

    async def process_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        raw_content: str,
        source_type: str,
        event_timestamp: Optional[datetime] = None,
        source_ref: Optional[str] = None,
        source_engineer_id: Optional[str] = None,
        explicit_entity_refs: Optional[list[str]] = None,
    ) -> dict:
        """Full six-stage discovery loop for a single event.

        Stage 1: Ingest & Enrich
        Stage 2: Score (snap evaluation)
        Stage 3: Detect (surprise, conflicts)
        Stage 4: Generate (hypotheses)
        Stage 5: Learn (calibration feedback integration)
        Stage 6: Adapt (meta-memory updates)
        """
        result: dict[str, Any] = {"tenant_id": tenant_id, "stages": {}}

        # Stage 1: Ingest & Enrich
        fragment = await self._enrichment.enrich(
            session, tenant_id, raw_content, source_type,
            event_timestamp=event_timestamp,
            source_ref=source_ref,
            source_engineer_id=source_engineer_id,
            explicit_entity_refs=explicit_entity_refs,
        )
        result["fragment_id"] = str(fragment.id)
        result["stages"]["enrich"] = {
            "status": "complete",
            "mask_semantic": fragment.mask_semantic,
            "mask_topological": fragment.mask_topological,
            "mask_operational": fragment.mask_operational,
            "entity_count": len(fragment.extracted_entities or []),
        }

        # Stage 2: Score
        snap_result = await self._snap.evaluate(session, fragment, tenant_id)
        result["stages"]["score"] = snap_result

        # Process affinities into accumulation graph
        for aff in snap_result.get("affinities", []):
            await self._accumulation.add_or_update_edge(
                session, tenant_id,
                fragment.id, aff["fragment_id"],
                aff["score"], aff.get("failure_mode", ""),
            )

        # Near-miss boost
        for nm in snap_result.get("near_misses", []):
            await self._decay.apply_near_miss_boost(session, nm["fragment_id"], tenant_id)

        # Stage 3: Detect
        detect_results: dict[str, Any] = {}

        # Surprise Engine: process each snap decision
        from backend.app.models.abeyance_orm import SnapDecisionRecordORM
        from sqlalchemy import select as sa_select
        sdr_stmt = (
            sa_select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.new_fragment_id == fragment.id,
                SnapDecisionRecordORM.tenant_id == tenant_id,
            )
        )
        sdr_result = await session.execute(sdr_stmt)
        sdrs = list(sdr_result.scalars().all())

        surprise_events = []
        for sdr in sdrs:
            se = await self._surprise.process_snap_decision(session, tenant_id, sdr)
            if se:
                surprise_events.append(str(se.id))
        detect_results["surprise_events"] = surprise_events

        # Cluster detection
        clusters = await self._accumulation.detect_and_evaluate_clusters(
            session, tenant_id, trigger_fragment_id=fragment.id,
        )
        detect_results["clusters"] = clusters

        result["stages"]["detect"] = detect_results

        # Stage 4: Generate hypotheses from surprise events
        generate_results: dict[str, Any] = {}
        for se_id_str in surprise_events:
            from uuid import UUID as _UUID
            await self._hypothesis.enqueue_trigger(
                session, tenant_id, "SURPRISE_EVENT", _UUID(se_id_str),
                context={"fragment_id": str(fragment.id)},
            )

        hypotheses = await self._hypothesis.process_queue(session, tenant_id)
        generate_results["hypotheses_generated"] = len(hypotheses)
        result["stages"]["generate"] = generate_results

        # Stage 5: Learn — integrate calibrated weights
        try:
            calibrated = await self._calibration.get_all_calibrated_weights(session, tenant_id)
            if calibrated:
                self._snap.set_weight_overrides(calibrated)
        except Exception:
            logger.debug("Calibration weight integration skipped", exc_info=True)

        result["stages"]["learn"] = {"calibrated_profiles": len(calibrated) if 'calibrated' in dir() else 0}

        # Stage 6: Adapt — meta-memory (async, best-effort)
        try:
            bias = await self._meta_memory.compute_bias(session, tenant_id)
            result["stages"]["adapt"] = {"bias_areas": len(bias)}
        except Exception:
            result["stages"]["adapt"] = {"status": "skipped"}

        await session.flush()
        return result

    async def run_background_jobs(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> dict:
        """Run periodic background discovery jobs.

        Scheduled separately from event processing.
        """
        results: dict[str, Any] = {}

        # Ignorance mapping scan
        try:
            results["ignorance"] = await self._ignorance.run_scan(session, tenant_id)
        except Exception:
            logger.warning("Ignorance scan failed", exc_info=True)
            results["ignorance"] = {"status": "failed"}

        # Bridge detection
        try:
            bridges = await self._bridge.detect_bridges(session, tenant_id)
            results["bridges"] = {"count": len(bridges)}
            for b in bridges:
                await self._hypothesis.enqueue_trigger(
                    session, tenant_id, "BRIDGE_DISCOVERY", b.id,
                    context={"severity": b.severity},
                )
        except Exception:
            logger.warning("Bridge detection failed", exc_info=True)
            results["bridges"] = {"status": "failed"}

        # Pattern conflict detection
        try:
            conflicts = await self._conflict.scan(session, tenant_id)
            results["conflicts"] = {"count": len(conflicts)}
        except Exception:
            logger.warning("Conflict detection failed", exc_info=True)
            results["conflicts"] = {"status": "failed"}

        # Causal direction analysis
        try:
            results["causal"] = await self._causal.run_analysis(session, tenant_id)
        except Exception:
            logger.warning("Causal analysis failed", exc_info=True)
            results["causal"] = {"status": "failed"}

        # Pattern compression
        from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3
        for profile in WEIGHT_PROFILES_V3:
            try:
                await self._compressor.analyze(session, tenant_id, profile)
            except Exception:
                logger.debug("Compression analysis failed for %s", profile)

        # Counterfactual simulation
        try:
            results["counterfactual"] = await self._counterfactual.run_batch(session, tenant_id)
        except Exception:
            logger.warning("Counterfactual sim failed", exc_info=True)
            results["counterfactual"] = {"status": "failed"}

        # Evolutionary patterns
        for profile in WEIGHT_PROFILES_V3:
            try:
                await self._evolution.evolve_generation(session, tenant_id, profile)
            except Exception:
                logger.debug("Evolution failed for %s", profile)

        # Hypothesis expiration
        try:
            expired = await self._hypothesis.expire_hypotheses(session, tenant_id)
            results["hypotheses_expired"] = expired
        except Exception:
            logger.debug("Hypothesis expiration failed")

        await session.flush()
        return results
