"""
Pydantic schemas for the Abeyance Memory subsystem.

Implements request/response models for the API endpoints specified in
ABEYANCE_MEMORY_LLD.md §14.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---- Enums (LLD §5, §8, §13) ----

class SourceType(str, Enum):
    """Fragment source types with distinct decay profiles (LLD §5)."""
    TICKET_TEXT = "TICKET_TEXT"
    ALARM = "ALARM"
    TELEMETRY_EVENT = "TELEMETRY_EVENT"
    CLI_OUTPUT = "CLI_OUTPUT"
    CHANGE_RECORD = "CHANGE_RECORD"
    CMDB_DELTA = "CMDB_DELTA"


class SnapStatus(str, Enum):
    """Fragment lifecycle states (LLD §5, remediated per Forensic Audit).

    State machine:
        INGESTED → ACTIVE → NEAR_MISS/SNAPPED/STALE → EXPIRED → COLD
        SNAPPED is terminal (INV-5).
    """
    INGESTED = "INGESTED"
    ACTIVE = "ACTIVE"
    NEAR_MISS = "NEAR_MISS"
    SNAPPED = "SNAPPED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    COLD = "COLD"


class EntityDomain(str, Enum):
    """Network entity domains (LLD §5)."""
    RAN = "RAN"
    TRANSPORT = "TRANSPORT"
    CORE = "CORE"
    IP = "IP"
    VNF = "VNF"
    SITE = "SITE"


class EntityOrigin(str, Enum):
    """Shadow Topology entity origin (LLD §8)."""
    CMDB_DECLARED = "CMDB_DECLARED"
    PEDKAI_DISCOVERED = "PEDKAI_DISCOVERED"
    PEDKAI_CORRECTED = "PEDKAI_CORRECTED"


class FailureMode(str, Enum):
    """Dark Graph divergence types (LLD §6 Step 3)."""
    DARK_NODE = "DARK_NODE"
    PHANTOM_NODE = "PHANTOM_NODE"
    DARK_EDGE = "DARK_EDGE"
    PHANTOM_EDGE = "PHANTOM_EDGE"
    IDENTITY_MUTATION = "IDENTITY_MUTATION"
    DARK_ATTRIBUTE = "DARK_ATTRIBUTE"


class DiscoveryType(str, Enum):
    """Discovery types for the value attribution ledger (LLD §13)."""
    DARK_NODE = "DARK_NODE"
    DARK_EDGE = "DARK_EDGE"
    PHANTOM_CI = "PHANTOM_CI"
    IDENTITY_MUTATION = "IDENTITY_MUTATION"
    DARK_ATTRIBUTE = "DARK_ATTRIBUTE"


class ValueEventType(str, Enum):
    """Value event types (LLD §13)."""
    INCIDENT_RESOLUTION = "INCIDENT_RESOLUTION"
    MTTR_REDUCTION = "MTTR_REDUCTION"
    LICENCE_SAVING = "LICENCE_SAVING"
    OUTAGE_PREVENTION = "OUTAGE_PREVENTION"
    DARK_GRAPH_REDUCTION = "DARK_GRAPH_REDUCTION"


class DiscoveryStatus(str, Enum):
    """Discovery ledger entry status (LLD §13)."""
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


# ---- Source type characteristics (LLD §5 table) ----

SOURCE_TYPE_DEFAULTS: dict[str, dict[str, float]] = {
    "TICKET_TEXT": {"base_relevance": 0.9, "decay_tau": 270.0},
    "ALARM": {"base_relevance": 0.7, "decay_tau": 90.0},
    "TELEMETRY_EVENT": {"base_relevance": 0.6, "decay_tau": 60.0},
    "CLI_OUTPUT": {"base_relevance": 0.7, "decay_tau": 180.0},
    "CHANGE_RECORD": {"base_relevance": 0.8, "decay_tau": 365.0},
    "CMDB_DELTA": {"base_relevance": 0.7, "decay_tau": 90.0},
}


# ---- Request Models ----

class RawEvidence(BaseModel):
    """Raw evidence payload for the enrichment chain (LLD §6)."""
    content: str
    source_type: SourceType
    source_ref: Optional[str] = None
    source_engineer_id: Optional[str] = None
    entity_refs: list[str] = Field(default_factory=list, description="Explicit entity identifiers")
    event_timestamp: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AbeyanceFragmentCreate(BaseModel):
    """Ingest request for the /abeyance/ingest endpoint."""
    tenant_id: str
    evidence: RawEvidence


# ---- Internal Models ----

class TemporalContext(BaseModel):
    """Temporal sub-vector components (LLD §7).

    Encodes cyclical time dimensions using sinusoidal encoding and
    operational time features for the 256-dim temporal sub-vector.
    """
    norm_timestamp: float = 0.0
    time_of_day_sin: float = 0.0
    time_of_day_cos: float = 0.0
    day_of_week_sin: float = 0.0
    day_of_week_cos: float = 0.0
    change_proximity: float = 0.0  # Gaussian: exp(-dist_h^2 / 2*24^2)
    vendor_upgrade_recency: float = 0.0  # exp(-days_since / 30)
    traffic_load_ratio: float = 0.0  # load vs 7-day baseline (0-2)
    seasonal_sin: float = 0.0
    seasonal_cos: float = 0.0


class OperationalFingerprint(BaseModel):
    """Operational context at time of evidence (LLD §6 Step 2)."""
    change_proximity: dict[str, Any] = Field(default_factory=dict)
    vendor_upgrade: dict[str, Any] = Field(default_factory=dict)
    traffic_cycle: dict[str, Any] = Field(default_factory=dict)
    concurrent_alarms: dict[str, Any] = Field(default_factory=dict)
    open_incidents: list[str] = Field(default_factory=list)

    @property
    def change_proximity_gaussian(self) -> float:
        """Gaussian distance to nearest change window."""
        import math
        hours = self.change_proximity.get("nearest_change_hours")
        if hours is None:
            return 0.0
        return math.exp(-(hours ** 2) / (2 * 24 ** 2))

    @property
    def vendor_upgrade_decay(self) -> float:
        """Exponential decay from last vendor upgrade."""
        import math
        days = self.vendor_upgrade.get("days_since_upgrade")
        if days is None:
            return 0.0
        return math.exp(-days / 30.0)

    @property
    def traffic_load_ratio(self) -> float:
        """Traffic load ratio vs baseline."""
        return self.traffic_cycle.get("load_ratio_vs_baseline", 0.0)


class FailureModeTag(BaseModel):
    """Individual failure mode classification (LLD §6 Step 3)."""
    divergence_type: str
    confidence: float = 0.0
    rationale: str = ""
    candidate_entities: list[str] = Field(default_factory=list)


class ScoredPair(BaseModel):
    """Scored fragment pair from snap evaluation (LLD §9 Stage 2)."""
    stored_fragment_id: UUID
    score: float
    failure_mode: str


class SnapResult(BaseModel):
    """Result of snap evaluation (LLD §9 Stage 3)."""
    snaps: list[ScoredPair] = Field(default_factory=list)
    near_misses: list[ScoredPair] = Field(default_factory=list)
    affinities: list[ScoredPair] = Field(default_factory=list)


# ---- Response Models ----

class AbeyanceFragmentResponse(BaseModel):
    """Full fragment response with enrichment data."""
    id: UUID
    tenant_id: str
    source_type: str
    raw_content: Optional[str] = None
    extracted_entities: list[Any] = Field(default_factory=list)
    topological_neighbourhood: dict[str, Any] = Field(default_factory=dict)
    operational_fingerprint: dict[str, Any] = Field(default_factory=dict)
    failure_mode_tags: list[Any] = Field(default_factory=list)
    temporal_context: dict[str, Any] = Field(default_factory=dict)
    event_timestamp: Optional[datetime] = None
    ingestion_timestamp: Optional[datetime] = None
    base_relevance: float = 1.0
    current_decay_score: float = 1.0
    near_miss_count: int = 0
    snap_status: str = "ABEYANCE"
    snapped_hypothesis_id: Optional[UUID] = None
    source_ref: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AbeyanceFragmentSummary(BaseModel):
    """Compact fragment for list responses (no embeddings)."""
    id: UUID
    tenant_id: str
    source_type: str
    snap_status: str
    current_decay_score: float
    near_miss_count: int
    event_timestamp: Optional[datetime] = None
    created_at: Optional[datetime] = None
    source_ref: Optional[str] = None

    class Config:
        from_attributes = True


class SnapHistoryEntry(BaseModel):
    """Snap event record."""
    fragment_id: UUID
    snapped_to: Optional[UUID] = None
    snap_score: float = 0.0
    failure_mode: Optional[str] = None
    snapped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccumulationEdgeResponse(BaseModel):
    """Accumulation graph edge."""
    id: UUID
    fragment_a_id: UUID
    fragment_b_id: UUID
    affinity_score: float
    strongest_failure_mode: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccumulationClusterResponse(BaseModel):
    """Detected accumulation cluster (LLD §10)."""
    cluster_id: str
    member_fragment_ids: list[UUID]
    member_count: int
    cluster_score: float
    strongest_failure_mode: Optional[str] = None


class ShadowEntityResponse(BaseModel):
    """Shadow Topology entity."""
    id: UUID
    tenant_id: str
    entity_identifier: str
    entity_domain: Optional[str] = None
    origin: str
    enrichment_value: float = 0.0
    first_seen: Optional[datetime] = None
    last_evidence: Optional[datetime] = None

    class Config:
        from_attributes = True


class ShadowRelationshipResponse(BaseModel):
    """Shadow Topology relationship."""
    id: UUID
    from_entity_id: UUID
    to_entity_id: UUID
    relationship_type: str
    origin: str
    confidence: float
    exported_to_cmdb: bool = False
    cmdb_reference_tag: Optional[str] = None

    class Config:
        from_attributes = True


class ShadowNeighbourhoodResponse(BaseModel):
    """N-hop neighbourhood expansion result (LLD §8)."""
    center_entity: str
    entities: list[ShadowEntityResponse] = Field(default_factory=list)
    relationships: list[ShadowRelationshipResponse] = Field(default_factory=list)
    max_hops: int = 2


class CmdbExportResponse(BaseModel):
    """CMDB export result."""
    export_id: UUID
    cmdb_reference_tag: str
    exported_at: datetime


class DiscoveryLedgerResponse(BaseModel):
    """Discovery ledger entry."""
    id: UUID
    tenant_id: str
    hypothesis_id: Optional[UUID] = None
    discovery_type: str
    discovered_entities: list[Any] = Field(default_factory=list)
    cmdb_reference_tag: Optional[str] = None
    discovered_at: Optional[datetime] = None
    discovery_confidence: float = 0.0
    status: str = "ACTIVE"

    class Config:
        from_attributes = True


class ValueEventResponse(BaseModel):
    """Value event entry."""
    id: UUID
    tenant_id: str
    ledger_entry_id: UUID
    event_type: str
    event_at: Optional[datetime] = None
    attributed_value_hours: Optional[float] = None
    attributed_value_currency: Optional[float] = None
    attribution_rationale: Optional[str] = None

    class Config:
        from_attributes = True


class ValueReportResponse(BaseModel):
    """Quarterly/cumulative value attribution report (LLD §13)."""
    tenant_id: str
    period: str
    total_discoveries: int = 0
    mttr_hours_saved: float = 0.0
    licence_savings_currency: float = 0.0
    illumination_ratio: float = 0.0
    dark_graph_reduction_index: float = 0.0
    discovery_breakdown: dict[str, int] = Field(default_factory=dict)
    value_events: list[ValueEventResponse] = Field(default_factory=list)


class IlluminationRatioResponse(BaseModel):
    """Current illumination ratio metric (LLD §13 Rule 5)."""
    tenant_id: str
    ratio: float = 0.0
    incidents_with_pedkai_entities: int = 0
    total_incidents: int = 0


class DarkGraphIndexResponse(BaseModel):
    """Dark Graph Reduction Index (LLD §13 Rule 6)."""
    tenant_id: str
    index: float = 0.0
    current_divergences: int = 0
    baseline_divergences: int = 0


class IncidentReconstructionResponse(BaseModel):
    """Reconstructed incident timeline from fragment history."""
    incident_id: str
    tenant_id: str
    fragments: list[AbeyanceFragmentSummary] = Field(default_factory=list)
    snaps: list[SnapHistoryEntry] = Field(default_factory=list)
    clusters: list[AccumulationClusterResponse] = Field(default_factory=list)
    reconstructed_timeline: list[dict[str, Any]] = Field(default_factory=list)


# ---- v3 Discovery Loop Response Models ----

class DiscoveryLoopResponse(BaseModel):
    """Full six-stage discovery loop result (LLD v3.0 §12)."""
    tenant_id: str
    fragment_id: str
    stages: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class DiscoveryBackgroundResponse(BaseModel):
    """Background discovery jobs result."""
    tenant_id: str
    results: dict[str, Any] = Field(default_factory=dict)


class DiscoveryStatusResponse(BaseModel):
    """Health status of v3 discovery mechanisms."""
    tenant_id: str
    tvec_status: dict[str, Any] = Field(default_factory=dict)
    tslam_status: dict[str, Any] = Field(default_factory=dict)
    mechanisms: dict[str, str] = Field(default_factory=dict)

