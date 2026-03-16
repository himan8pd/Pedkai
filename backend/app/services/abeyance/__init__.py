"""
Abeyance Memory Subsystem — service layer.

v3.0: Adds DiscoveryLoop, TVecService, TSLAMService, EnrichmentChainV3,
SnapEngineV3, and 14 discovery mechanisms on top of the v2 foundation.

Public API:
    v2 (retained):
        - EnrichmentChain, SnapEngine, AccumulationGraph, DecayEngine
        - ShadowTopologyService, ValueAttributionService
        - IncidentReconstructionService, MaintenanceService
        - ProvenanceLogger, RedisNotifier

    v3 (new):
        - TVecService, TSLAMService
        - EnrichmentChainV3, SnapEngineV3
        - DiscoveryLoop (6-stage orchestrator)
        - 14 discovery mechanisms (Layers 2–5)
"""

from backend.app.services.abeyance.events import (
    ProvenanceLogger,
    RedisNotifier,
)
from backend.app.services.abeyance.enrichment_chain import EnrichmentChain
from backend.app.services.abeyance.snap_engine import SnapEngine
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


def create_abeyance_services(
    redis_client=None,
    llm_service=None,
) -> dict:
    """Factory function to create all abeyance services with shared dependencies.

    Returns both v2 and v3 services. The v3 discovery loop orchestrates
    all 14 discovery mechanisms through the five-layer cognitive architecture.

    Usage:
        services = create_abeyance_services(redis_client=redis, llm_service=llm)
        enrichment = services["enrichment"]        # v2
        discovery_loop = services["discovery_loop"] # v3
    """
    # Shared infrastructure
    provenance = ProvenanceLogger()
    notifier = RedisNotifier(redis_client=redis_client)
    shadow_topology = ShadowTopologyService()

    # v2 services (retained for backward compat)
    decay_engine = DecayEngine(provenance=provenance, notifier=notifier)
    snap_engine = SnapEngine(provenance=provenance, notifier=notifier)
    accumulation_graph = AccumulationGraph(provenance=provenance, notifier=notifier)
    enrichment = EnrichmentChain(
        provenance=provenance,
        llm_service=llm_service,
        shadow_topology=shadow_topology,
    )
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
    expectation_violation = ExpectationViolationDetector(temporal_sequence)
    causal_direction = CausalDirectionTester()

    # Layer 4
    pattern_compressor = PatternCompressor()
    counterfactual_sim = CounterfactualSimulator(snap_engine_v3)

    # Layer 5
    meta_memory = MetaMemoryService()
    evolutionary_patterns = EvolutionaryPatternService()

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
        # v2 (backward compat)
        "provenance": provenance,
        "notifier": notifier,
        "enrichment": enrichment,
        "snap_engine": snap_engine,
        "accumulation_graph": accumulation_graph,
        "decay_engine": decay_engine,
        "shadow_topology": shadow_topology,
        "value_attribution": value_attribution,
        "incident_reconstruction": incident_reconstruction,
        "maintenance": maintenance,
        # v3
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
    # v2
    "ProvenanceLogger",
    "RedisNotifier",
    "EnrichmentChain",
    "SnapEngine",
    "AccumulationGraph",
    "DecayEngine",
    "ShadowTopologyService",
    "ValueAttributionService",
    "IncidentReconstructionService",
    "MaintenanceService",
    # v3
    "TVecService",
    "TSLAMService",
    "EnrichmentChainV3",
    "SnapEngineV3",
    "DiscoveryLoop",
    "create_abeyance_services",
]
