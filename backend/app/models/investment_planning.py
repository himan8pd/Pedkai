"""
ORM models for AI-Driven Capacity Planning.
Tracks Densification Requests and Optimized Investment Plans.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, Float, String, text, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from backend.app.core.database import Base

class DensificationRequestORM(Base):
    """
    Represents a request to optimize network capacity in a given region.
    """
    __tablename__ = "densification_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    tenant_id = Column(String(255), nullable=False, index=True)
    region_name = Column(String(255), nullable=False)
    budget_limit = Column(Float, nullable=False)
    target_kpi = Column(String(100), default="prb_utilization") # e.g., congestion reduction
    status = Column(String(50), default="pending") # pending | processing | completed | failed
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=text("now()"), nullable=False)
    
    # Input parameters for the optimization
    parameters = Column(JSONB, nullable=False, default=dict) # {min_sites, max_sites, spectrum_priority}

class InvestmentPlanORM(Base):
    """
    The output of the Capacity Engine: A specific deployment plan.
    """
    __tablename__ = "investment_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    request_id = Column(UUID(as_uuid=True), ForeignKey("densification_requests.id"), nullable=False)
    total_estimated_cost = Column(Float, nullable=False)
    expected_kpi_improvement = Column(Float, nullable=False) # e.g., 25% reduction in congestion
    rationale = Column(Text, nullable=False)
    
    # The actual sites to be deployed
    site_placements = Column(JSONB, nullable=False) # List of {lat, lon, size, cost, backhaul_type}
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=text("now()"), nullable=False)
