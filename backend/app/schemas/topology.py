"""
Topology API Schemas.

Shared contract used by: WS1 (topology API), WS3 (frontend), WS4 (correlation).
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class EntityResponse(BaseModel):
    """A single network entity in the topology graph."""
    id: str | UUID
    external_id: str
    name: str
    entity_type: str
    tenant_id: str
    properties: Optional[Dict[str, Any]] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RelationshipResponse(BaseModel):
    """A relationship between two entities."""
    id: UUID
    source_entity_id: str | UUID
    target_entity_id: str | UUID
    relationship_type: str
    properties: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class TopologyHealth(BaseModel):
    """Topology staleness and completeness metrics."""
    total_entities: int
    stale_entities: int  # Entities where last_synced_at > threshold
    status: str = "healthy"
    completeness_pct: float = Field(ge=0.0, le=100.0)
    staleness_threshold_minutes: int = 60
    staleness_threshold_days: Optional[int] = None


class TopologyGraphResponse(BaseModel):
    """Full topology graph for a tenant."""
    tenant_id: str
    entities: List[EntityResponse]
    relationships: List[RelationshipResponse]
    topology_health: Optional[TopologyHealth] = None


class ImpactTreeNode(BaseModel):
    """A node in the impact analysis tree."""
    entity_id: str | UUID
    entity_name: str
    entity_type: str
    external_id: str
    direction: str  # "upstream" or "downstream"
    relationship_type: str
    depth: int
    children: Optional[List["ImpactTreeNode"]] = None
    revenue_at_risk: Optional[float] = None


class ImpactTreeResponse(BaseModel):
    """Impact analysis result."""
    root_entity_id: str | UUID
    root_entity_name: str
    root_entity_type: str
    upstream: List[ImpactTreeNode]
    downstream: List[ImpactTreeNode]
    total_customers_impacted: int = 0
    total_revenue_at_risk: Optional[float] = None


# Rebuild forward refs
TopologyGraphResponse.model_rebuild()
ImpactTreeNode.model_rebuild()
