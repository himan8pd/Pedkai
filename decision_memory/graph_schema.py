"""
Network Topology Graph Schema

Defines the network entities and their relationships for Pedkai.
This represents the "ontologically stable" layer that Jaya Gupta describes -
the nouns and verbs of the telco domain that are durable.

The graph is NOT stored in a graph database - it's represented as
relational data with relationship tables, enabling standard SQL queries
while preserving the graph semantics.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENTITY TYPES (Ontologically Stable Nouns)
# =============================================================================

class EntityType(str, Enum):
    """Types of network entities."""
    # RAN (Radio Access Network)
    GNODEB = "gnodeb"           # 5G base station
    ENODEB = "enodeb"           # 4G base station
    CELL = "cell"               # Individual cell/sector
    ANTENNA = "antenna"         # Physical antenna
    
    # Transport
    ROUTER = "router"
    SWITCH = "switch"
    FIBER_LINK = "fiber_link"
    MICROWAVE_LINK = "microwave_link"
    
    # Core Network
    AMF = "amf"                 # Access and Mobility Function
    UPF = "upf"                 # User Plane Function
    SMF = "smf"                 # Session Management Function
    VOICE_CORE = "voice_core"   # IMS/Voice Gateway
    SMSC = "smsc"               # Short Message Service Center
    
    # Fixed & Broadband
    BROADBAND_GATEWAY = "broadband_gateway"
    LANDLINE_EXCHANGE = "landline_exchange"
    
    # Services
    SERVICE = "service"
    SLICE = "slice"             # Network slice
    EMERGENCY_SERVICE = "emergency_service" # 911/999
    
    # Customers
    ENTERPRISE_CUSTOMER = "enterprise_customer"
    RESIDENTIAL_CUSTOMER = "residential_customer"
    SITE = "site"               # Customer site
    SLA = "sla"                 # Service Level Agreement


class RelationshipType(str, Enum):
    """Types of relationships between entities."""
    # Physical relationships
    HOSTS = "hosts"             # gNodeB hosts Cell
    CONNECTS_TO = "connects_to" # Physical connection
    PART_OF = "part_of"         # Is part of larger entity
    
    # Service relationships
    SERVES = "serves"           # Cell serves Customer Site
    DEPENDS_ON = "depends_on"   # Service depends on infrastructure
    COVERED_BY = "covered_by"   # Customer covered by SLA
    
    # Neighbor relationships
    NEIGHBOR = "neighbor"       # Cell is neighbor of Cell
    HANDOVER_TARGET = "handover_target"  # Handover relationship


# =============================================================================
# ENTITY MODELS
# =============================================================================

class NetworkEntity(BaseModel):
    """
    Base model for any network entity.
    
    Entities are the "nouns" of the telco domain - stable concepts
    that persist over time.
    """
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    entity_type: EntityType
    name: str
    external_id: Optional[str] = Field(
        None,
        description="ID from external system (OSS, NMS, etc.)"
    )
    
    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Status
    operational_status: str = Field(
        default="active",
        description="active, maintenance, degraded, down"
    )
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Flexible attributes (stored as JSONB)
    attributes: dict = Field(default_factory=dict)


class Cell(NetworkEntity):
    """A radio cell (sector) in the RAN."""
    entity_type: EntityType = EntityType.CELL
    
    # Cell-specific attributes
    pci: Optional[int] = Field(None, description="Physical Cell ID")
    technology: str = Field(default="5G", description="4G, 5G")
    frequency_band: Optional[str] = None
    azimuth: Optional[float] = None  # degrees
    downtilt: Optional[float] = None  # degrees
    tx_power_dbm: Optional[float] = None
    
    # Current metrics (snapshot)
    current_throughput_mbps: Optional[float] = None
    current_prb_utilization: Optional[float] = None
    connected_users: Optional[int] = None


class GNodeB(NetworkEntity):
    """A 5G base station (gNodeB)."""
    entity_type: EntityType = EntityType.GNODEB
    
    # gNodeB-specific attributes
    site_id: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    software_version: Optional[str] = None
    cell_count: int = 0


class EnterpriseCustomer(NetworkEntity):
    """An enterprise customer with SLAs."""
    entity_type: EntityType = EntityType.ENTERPRISE_CUSTOMER
    
    # Customer attributes
    customer_tier: str = Field(default="standard", description="standard, premium, platinum")
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None
    account_manager: Optional[str] = None


class SLA(NetworkEntity):
    """Service Level Agreement defining guarantees."""
    entity_type: EntityType = EntityType.SLA
    
    # SLA thresholds
    availability_target_pct: float = Field(default=99.9)
    latency_max_ms: Optional[float] = None
    throughput_min_mbps: Optional[float] = None
    mttr_max_hours: Optional[float] = Field(
        None,
        description="Maximum Mean Time To Repair"
    )
    
    # Penalty info
    penalty_per_violation_usd: Optional[float] = None


# =============================================================================
# RELATIONSHIP MODELS
# =============================================================================

class EntityRelationship(BaseModel):
    """
    Relationship between two entities.
    
    Relationships are the "verbs" of the telco domain - how entities
    connect to and depend on each other.
    """
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    
    # Source and target entities
    source_entity_id: UUID
    source_entity_type: EntityType
    target_entity_id: UUID
    target_entity_type: EntityType
    
    # Relationship type
    relationship_type: RelationshipType
    
    # Relationship attributes
    weight: Optional[float] = Field(
        None,
        description="Relationship strength/priority (0-1)"
    )
    attributes: dict = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


# =============================================================================
# GRAPH QUERIES
# =============================================================================

class ImpactQuery(BaseModel):
    """Query to find entities impacted by an issue."""
    source_entity_id: UUID
    relationship_types: list[RelationshipType] = Field(default_factory=list)
    max_hops: int = Field(default=3, ge=1, le=10)
    include_entity_types: list[EntityType] = Field(default_factory=list)


class DependencyQuery(BaseModel):
    """Query to find dependencies of an entity."""
    entity_id: UUID
    direction: str = Field(
        default="upstream",
        description="upstream (what this depends on) or downstream (what depends on this)"
    )
    max_depth: int = Field(default=5, ge=1, le=10)


# =============================================================================
# EXAMPLE TOPOLOGY
# =============================================================================

def create_sample_topology(tenant_id: str = "demo") -> dict:
    """
    Create a sample network topology for testing.
    
    Returns a dict with 'entities' and 'relationships' lists.
    """
    entities = []
    relationships = []
    
    # Create a gNodeB with 3 cells
    gnodeb = GNodeB(
        tenant_id=tenant_id,
        name="gNodeB-001",
        external_id="NE12345",
        latitude=51.5074,
        longitude=-0.1278,
        site_id="SITE-LON-001",
        vendor="Nokia",
        cell_count=3,
    )
    entities.append(gnodeb)
    
    # Create 3 cells
    for i in range(3):
        cell = Cell(
            tenant_id=tenant_id,
            name=f"Cell-001-{i+1}",
            external_id=f"CELL-{i+1}",
            latitude=51.5074,
            longitude=-0.1278,
            pci=100 + i,
            technology="5G",
            frequency_band="n78",
            azimuth=i * 120,  # 0, 120, 240 degrees
            downtilt=5.0,
        )
        entities.append(cell)
        
        # gNodeB hosts Cell
        relationships.append(EntityRelationship(
            tenant_id=tenant_id,
            source_entity_id=gnodeb.id,
            source_entity_type=EntityType.GNODEB,
            target_entity_id=cell.id,
            target_entity_type=EntityType.CELL,
            relationship_type=RelationshipType.HOSTS,
        ))
    
    # Create an enterprise customer with SLA
    customer = EnterpriseCustomer(
        tenant_id=tenant_id,
        name="Acme Corp",
        external_id="CUST-001",
        customer_tier="platinum",
    )
    entities.append(customer)
    
    sla = SLA(
        tenant_id=tenant_id,
        name="Acme Platinum SLA",
        availability_target_pct=99.99,
        latency_max_ms=10,
        throughput_min_mbps=500,
        mttr_max_hours=2,
        penalty_per_violation_usd=10000,
    )
    entities.append(sla)
    
    # Customer covered by SLA
    relationships.append(EntityRelationship(
        tenant_id=tenant_id,
        source_entity_id=customer.id,
        source_entity_type=EntityType.ENTERPRISE_CUSTOMER,
        target_entity_id=sla.id,
        target_entity_type=EntityType.SLA,
        relationship_type=RelationshipType.COVERED_BY,
    ))
    
    # Cell serves Customer
    for entity in entities:
        if isinstance(entity, Cell):
            relationships.append(EntityRelationship(
                tenant_id=tenant_id,
                source_entity_id=entity.id,
                source_entity_type=EntityType.CELL,
                target_entity_id=customer.id,
                target_entity_type=EntityType.ENTERPRISE_CUSTOMER,
                relationship_type=RelationshipType.SERVES,
            ))
            break  # Just one cell serves this customer
    
    return {
        "entities": entities,
        "relationships": relationships,
    }


if __name__ == "__main__":
    # Test the sample topology
    topology = create_sample_topology()
    
    print("🌐 Sample Network Topology")
    print("=" * 50)
    
    print("\n📡 Entities:")
    for entity in topology["entities"]:
        print(f"  - {entity.entity_type.value}: {entity.name}")
    
    print("\n🔗 Relationships:")
    for rel in topology["relationships"]:
        print(f"  - {rel.source_entity_type.value} --[{rel.relationship_type.value}]--> {rel.target_entity_type.value}")
