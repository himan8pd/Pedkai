from datetime import datetime
from uuid import UUID
import uuid

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Integer, Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from backend.app.core.database import Base

class ServicePlanORM(Base):
    __tablename__ = "bss_service_plans"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False) # e.g., "Enterprise Gold 5G"
    tier = Column(String(50), nullable=False) # GOLD, SILVER, BRONZE
    monthly_fee = Column(Float, nullable=False)
    sla_guarantee = Column(String(255), nullable=True) # e.g., "99.999% Availability"
    
    from datetime import timezone
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class BillingAccountORM(Base):
    __tablename__ = "bss_billing_accounts"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True)
    
    plan_id = Column(PG_UUID(as_uuid=True), ForeignKey("bss_service_plans.id"), nullable=False)
    
    account_status = Column(String(50), default="ACTIVE") # ACTIVE, SUSPENDED, DELINQUENT
    avg_monthly_revenue = Column(Float, default=0.0)
    contract_end_date = Column(DateTime, nullable=True)
    
    last_billing_dispute = Column(DateTime, nullable=True)
    
    # Relationships
    service_plan = relationship("ServicePlanORM") 
    # customer relationship is inverse from CustomerORM, or we can add it here if needed.
