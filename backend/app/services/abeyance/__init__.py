"""
Abeyance Memory Subsystem — service layer.

Remediated per Forensic Audit (docs/ABEYANCE_MEMORY_FORENSIC_AUDIT.md).
All services enforce the 13 hard invariants defined in Phase 2.

Public API:
    - EnrichmentChain: 4-step enrichment pipeline
    - SnapEngine: 3-stage snap evaluation with bounded scoring
    - AccumulationGraph: LME-scored cluster detection
    - DecayEngine: Bounded exponential decay with audit trail
    - ShadowTopologyService: Cycle-guarded BFS with tenant isolation
    - ValueAttributionService: Discovery ledger and value tracking
    - IncidentReconstructionService: Forensic timeline assembly
    - MaintenanceService: Bounded background jobs
    - ProvenanceLogger: Append-only event logging
    - RedisNotifier: Best-effort notification (not source of truth)
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


def create_abeyance_services(
    redis_client=None,
    llm_service=None,
) -> dict:
    """Factory function to create all abeyance services with shared dependencies.

    Usage:
        services = create_abeyance_services(redis_client=redis, llm_service=llm)
        enrichment = services["enrichment"]
        snap_engine = services["snap_engine"]
    """
    provenance = ProvenanceLogger()
    notifier = RedisNotifier(redis_client=redis_client)
    shadow_topology = ShadowTopologyService()

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

    return {
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
    }


__all__ = [
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
    "create_abeyance_services",
]
