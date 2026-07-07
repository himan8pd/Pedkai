"""
Abeyance Memory Subsystem — service layer.

v3.0: Canonical implementation. All enrichment and snap evaluation uses v3.
DiscoveryLoop orchestrates 14 discovery mechanisms through the five-layer
cognitive architecture.

Public API:
    Shared infrastructure:
        - AccumulationGraph, DecayEngine
        - ShadowTopologyService, ValueAttributionService
        - IncidentReconstructionService, MaintenanceService
        - ProvenanceLogger, RedisNotifier

    v3 (canonical):
        - TVecService, TSLAMService
        - EnrichmentChainV3, SnapEngineV3
        - DiscoveryLoop (6-stage orchestrator)
        - 14 discovery mechanisms (Layers 2–5)
"""

from backend.app.services.abeyance.events import (
    ProvenanceLogger,
    RedisNotifier,
)
from backend.app.services.abeyance.accumulation_graph import AccumulationGraph
from backend.app.services.abeyance.decay_engine import DecayEngine
from backend.app.services.abeyance.shadow_topology import ShadowTopologyService
from backend.app.services.abeyance.value_attribution import ValueAttributionService
from backend.app.services.abeyance.incident_reconstruction import IncidentReconstructionService
from backend.app.services.abeyance.maintenance import MaintenanceService

# v3
from backend.app.services.abeyance.tvec_service import TVecService
from backend.app.services.abeyance.tslam_service import TSLAMService
from backend.app.services.abeyance.enrichment_chain_v3 import EnrichmentChainV3
from backend.app.services.abeyance.snap_engine_v3 import SnapEngineV3
from backend.app.services.abeyance.discovery_loop import DiscoveryLoop

# Discovery mechanisms
from backend.app.services.abeyance.discovery.surprise_engine import SurpriseEngine
from backend.app.services.abeyance.discovery.ignorance_mapper import IgnoranceMapper
from backend.app.services.abeyance.discovery.negative_evidence import NegativeEvidenceService
from backend.app.services.abeyance.discovery.bridge_detector import BridgeDetector
from backend.app.services.abeyance.discovery.outcome_calibration import OutcomeCalibrationService
from backend.app.services.abeyance.discovery.pattern_conflict import PatternConflictDetector
from backend.app.services.abeyance.discovery.temporal_sequence import TemporalSequenceModeller
from backend.app.services.abeyance.discovery.hypothesis_generator import HypothesisGenerator
from backend.app.services.abeyance.discovery.expectation_violation import ExpectationViolationDetector
from backend.app.services.abeyance.discovery.causal_direction import CausalDirectionTester
from backend.app.services.abeyance.discovery.pattern_compression import PatternCompressor
from backend.app.services.abeyance.discovery.counterfactual_sim import CounterfactualSimulator
from backend.app.services.abeyance.discovery.meta_memory import MetaMemoryService
from backend.app.services.abeyance.discovery.evolutionary_patterns import EvolutionaryPatternService

import logging
import os

logger = logging.getLogger(__name__)

# Experimental discovery mechanisms that are not yet validated. They are gated
# behind the ABEYANCE_EXPERIMENTAL_MECHANISMS csv env var (default "" = all
# disabled). When disabled, a _DisabledMechanism stub is substituted so the
# discovery loop runs end-to-end without exercising the unvalidated code paths.
EXPERIMENTAL_MECHANISMS = frozenset(
    {"meta_memory", "counterfactual_sim", "expectation_violation", "pattern_compressor"}
)


class _DisabledMechanism:
    """Inert stand-in for an experimental mechanism that is turned off.

    Every async method returns a benign, side-effect-free value ({} / None)
    matching what the discovery loop expects (e.g. compute_bias/run_batch are
    consumed via len(...), so they must return a dict). A DEBUG line is logged
    once per call so the disabled path is observable without noise.
    """

    def __init__(self, mechanism_name: str):
        self._mechanism_name = mechanism_name

    async def _noop(self, method: str, result):
        logger.debug(
            "Experimental mechanism '%s' is disabled; %s is a no-op",
            self._mechanism_name,
            method,
        )
        return result

    # meta_memory (MetaMemoryService)
    async def compute_bias(self, *args, **kwargs) -> dict:
        return await self._noop("compute_bias", {})

    async def check_activation(self, *args, **kwargs) -> bool:
        return await self._noop("check_activation", False)

    async def record_outcome(self, *args, **kwargs) -> None:
        return await self._noop("record_outcome", None)

    # counterfactual_sim (CounterfactualSimulator)
    async def run_batch(self, *args, **kwargs) -> dict:
        return await self._noop("run_batch", {})

    async def enqueue_candidate(self, *args, **kwargs):
        return await self._noop("enqueue_candidate", None)

    # expectation_violation (ExpectationViolationDetector)
    async def check_transition(self, *args, **kwargs):
        return await self._noop("check_transition", None)

    # pattern_compressor (PatternCompressor)
    async def analyze(self, *args, **kwargs):
        return await self._noop("analyze", None)


def _experimental_enabled() -> frozenset:
    """Parse ABEYANCE_EXPERIMENTAL_MECHANISMS (csv) into a set of names."""
    raw = os.environ.get("ABEYANCE_EXPERIMENTAL_MECHANISMS", "")
    return frozenset(
        name.strip() for name in raw.split(",") if name.strip()
    )


def create_abeyance_services(
    redis_client=None,
    llm_service=None,
) -> dict:
    """Factory function to create all abeyance services with shared dependencies.

    Abeyance Memory 3.0 is the canonical implementation. All enrichment and
    snap evaluation is routed through v3 services.

    Usage:
        services = create_abeyance_services(redis_client=redis, llm_service=llm)
        enrichment = services["enrichment_v3"]
        snap_engine = services["snap_engine_v3"]
        discovery_loop = services["discovery_loop"]
    """
    # Shared infrastructure
    provenance = ProvenanceLogger()
    notifier = RedisNotifier(redis_client=redis_client)
    shadow_topology = ShadowTopologyService()

    # Shared services (used by v3 and maintenance)
    decay_engine = DecayEngine(provenance=provenance, notifier=notifier)
    accumulation_graph = AccumulationGraph(provenance=provenance, notifier=notifier)
    value_attribution = ValueAttributionService()
    incident_reconstruction = IncidentReconstructionService()
    maintenance = MaintenanceService(
        decay_engine=decay_engine,
        accumulation_graph=accumulation_graph,
        provenance=provenance,
    )

    # v3 services
    tvec = TVecService()
    tslam = TSLAMService()

    enrichment_v3 = EnrichmentChainV3(
        provenance=provenance,
        tvec_service=tvec,
        tslam_service=tslam,
        shadow_topology=shadow_topology,
        llm_service=llm_service,
    )
    snap_engine_v3 = SnapEngineV3(provenance=provenance, notifier=notifier)

    # Layer 2 discovery mechanisms
    surprise_engine = SurpriseEngine()
    ignorance_mapper = IgnoranceMapper()
    negative_evidence = NegativeEvidenceService(provenance=provenance)
    bridge_detector = BridgeDetector()
    outcome_calibration = OutcomeCalibrationService()
    pattern_conflict = PatternConflictDetector()
    temporal_sequence = TemporalSequenceModeller()

    # Layer 3
    hypothesis_generator = HypothesisGenerator(tslam_service=tslam)
    causal_direction = CausalDirectionTester()

    # Layer 5
    evolutionary_patterns = EvolutionaryPatternService()

    # Experimental mechanisms — constructed for real only when explicitly named
    # in ABEYANCE_EXPERIMENTAL_MECHANISMS; otherwise a _DisabledMechanism stub is
    # used so the unvalidated code paths stay dormant.
    enabled = _experimental_enabled()

    expectation_violation = (
        ExpectationViolationDetector(temporal_sequence)
        if "expectation_violation" in enabled
        else _DisabledMechanism("expectation_violation")
    )
    pattern_compressor = (
        PatternCompressor()
        if "pattern_compressor" in enabled
        else _DisabledMechanism("pattern_compressor")
    )
    counterfactual_sim = (
        CounterfactualSimulator(snap_engine_v3)
        if "counterfactual_sim" in enabled
        else _DisabledMechanism("counterfactual_sim")
    )
    meta_memory = (
        MetaMemoryService()
        if "meta_memory" in enabled
        else _DisabledMechanism("meta_memory")
    )

    # Discovery loop orchestrator
    discovery_loop = DiscoveryLoop(
        enrichment=enrichment_v3,
        snap_engine=snap_engine_v3,
        accumulation_graph=accumulation_graph,
        decay_engine=decay_engine,
        provenance=provenance,
        notifier=notifier,
        surprise_engine=surprise_engine,
        ignorance_mapper=ignorance_mapper,
        negative_evidence=negative_evidence,
        bridge_detector=bridge_detector,
        outcome_calibration=outcome_calibration,
        pattern_conflict=pattern_conflict,
        temporal_sequence=temporal_sequence,
        hypothesis_generator=hypothesis_generator,
        expectation_violation=expectation_violation,
        causal_direction=causal_direction,
        pattern_compressor=pattern_compressor,
        counterfactual_sim=counterfactual_sim,
        meta_memory=meta_memory,
        evolutionary_patterns=evolutionary_patterns,
    )

    return {
        # Shared infrastructure
        "provenance": provenance,
        "notifier": notifier,
        "accumulation_graph": accumulation_graph,
        "decay_engine": decay_engine,
        "shadow_topology": shadow_topology,
        "value_attribution": value_attribution,
        "incident_reconstruction": incident_reconstruction,
        "maintenance": maintenance,
        # v3 (canonical)
        "tvec": tvec,
        "tslam": tslam,
        "enrichment_v3": enrichment_v3,
        "snap_engine_v3": snap_engine_v3,
        "discovery_loop": discovery_loop,
        # Discovery mechanisms (exposed for direct access)
        "surprise_engine": surprise_engine,
        "ignorance_mapper": ignorance_mapper,
        "negative_evidence": negative_evidence,
        "bridge_detector": bridge_detector,
        "outcome_calibration": outcome_calibration,
        "pattern_conflict": pattern_conflict,
        "temporal_sequence": temporal_sequence,
        "hypothesis_generator": hypothesis_generator,
        "expectation_violation": expectation_violation,
        "causal_direction": causal_direction,
        "pattern_compressor": pattern_compressor,
        "counterfactual_sim": counterfactual_sim,
        "meta_memory": meta_memory,
        "evolutionary_patterns": evolutionary_patterns,
    }


__all__ = [
    # Shared infrastructure
    "ProvenanceLogger",
    "RedisNotifier",
    "AccumulationGraph",
    "DecayEngine",
    "ShadowTopologyService",
    "ValueAttributionService",
    "IncidentReconstructionService",
    "MaintenanceService",
    # v3 (canonical)
    "TVecService",
    "TSLAMService",
    "EnrichmentChainV3",
    "SnapEngineV3",
    "DiscoveryLoop",
    "create_abeyance_services",
]
