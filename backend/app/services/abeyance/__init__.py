"""
Abeyance Memory Subsystem — service layer.

Implements the long-horizon intelligence buffer described in the
Abeyance Memory LLD (docs/ABEYANCE_MEMORY_LLD.md).

Modules:
    shadow_topology    — Private topology graph (LLD §8)
    enrichment_chain   — 4-step evidence enrichment pipeline (LLD §6)
    snap_engine        — 3-stage fragment matching (LLD §9)
    accumulation_graph — Weak-affinity cluster detection (LLD §10)
    value_attribution  — Discovery ledger and value metrics (LLD §13)
    incident_reconstruction — Timeline assembly from fragment history
"""

from backend.app.services.abeyance.accumulation_graph import AccumulationGraphService
from backend.app.services.abeyance.enrichment_chain import EnrichmentChain
from backend.app.services.abeyance.incident_reconstruction import IncidentReconstructionService
from backend.app.services.abeyance.shadow_topology import (
    ShadowTopologyService,
    get_shadow_topology,
)
from backend.app.services.abeyance.snap_engine import SnapEngine
from backend.app.services.abeyance.value_attribution import ValueAttributionService

__all__ = [
    "AccumulationGraphService",
    "EnrichmentChain",
    "IncidentReconstructionService",
    "ShadowTopologyService",
    "SnapEngine",
    "ValueAttributionService",
    "get_shadow_topology",
]
