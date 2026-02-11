"""
ORM Models for Phase 14: Customer Experience Intelligence.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from backend.app.core.database import Base

class CustomerORM(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = Column(String(100), unique=True, nullable=False, index=True) # Vendor-provided customer ID
    name = Column(String(255), nullable=True)
    churn_risk_score = Column(Float, default=0.0) # 0.0 to 1.0
    associated_site_id = Column(String(255), nullable=True, index=True) # Primary site the customer uses
    tenant_id = Column(String(50), default="default", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class ProactiveCareORM(Base):
    __tablename__ = "proactive_care_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    anomaly_id = Column(UUID(as_uuid=True), nullable=True) # Linked to DecisionTraceORM.id if available
    channel = Column(String(50), default="simulation") # email | sms | simulation
    status = Column(String(50), default="triggered") # triggered | sent | failed
    message_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
