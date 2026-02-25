"""
Policy Engine ORM Models (P5.1)

Stores policy rules with versioning, audit trail, and explicit gates for autonomous execution.
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, Float, DateTime, Enum, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum

from backend.app.core.database import Base


class ActionDecision(PyEnum):
    """Decision outcome for policy evaluation"""
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"  # Requires human confirmation


class PolicyORM(Base):
    """
    Policy rules for autonomous execution gating.
    
    Each policy defines:
    - Allowed action types (cell_failover, connection_throttle, alarm_silence, qos_tune)
    - Blast-radius limits (max entities affected)
    - Confidence thresholds (min similarity score and success rate)
    - Confirmation window (seconds before auto-execute)
    - Version tracking (creation, modification timestamps)
    """
    __tablename__ = "policies"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)

    # Policy metadata
    name = Column(String(256), nullable=False)  # e.g., "cell_failover_tier1"
    description = Column(Text, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String(32), default="active", nullable=False)  # active, archived, draft
    
    # Versioning
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(256), nullable=True)  # User email or service name
    
    # Policy rules (JSON structure for flexibility)
    rules = Column(JSON, nullable=False)
    """
    Example rules:
    {
      "allowed_actions": ["cell_failover", "connection_throttle"],
      "blast_radius_limit": 100,
      "confidence_threshold": 0.85,
      "min_success_rate": 0.90,
      "confirmation_window_sec": 30,
      "auto_rollback_threshold_pct": 10,
      "allowed_entity_types": ["CELL", "SECTOR"],
      "restricted_vendors": ["huawei"]
    }
    """

    # Relationships
    evaluations = relationship("PolicyEvaluationORM", back_populates="policy", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Policy {self.name} v{self.version} for {self.tenant_id}>"


class PolicyEvaluationORM(Base):
    """
    Audit trail for policy evaluations.
    
    Tracks every time a policy is evaluated for an action,
    including the decision (ALLOW/DENY/CONFIRM) and reasoning.
    """
    __tablename__ = "policy_evaluations"

    id = Column(String(36), primary_key=True)
    policy_id = Column(String(36), ForeignKey("policies.id"), nullable=False)
    policy = relationship(PolicyORM, back_populates="evaluations")
    
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Request context
    action_type = Column(String(50), nullable=False)  # cell_failover, connection_throttle, etc.
    action_parameters = Column(JSON, nullable=True)
    
    # Decision details
    decision = Column(Enum(ActionDecision), nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)  # 0.0 - 1.0
    
    # Reasoning (which rules matched, which didn't)
    matched_rules = Column(JSON, nullable=True)
    """
    Example:
    {
      "blast_radius_check": {
        "passed": true,
        "entities_affected": 32,
        "limit": 100
      },
      "confidence_threshold_check": {
        "passed": true,
        "required": 0.85,
        "actual": 0.92
      }
    }
    """
    
    # Trace for distributed tracing
    trace_id = Column(String(100), nullable=True)
    
    # Timestamp
    evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    evaluated_by = Column(String(256), nullable=True)  # User email or automated service
    
    def __repr__(self):
        return f"<PolicyEvaluation {self.decision.value} for {self.action_type}>"


class PolicyVersionORM(Base):
    """
    Historical versions of policies for audit and rollback.
    
    Every time a policy is modified, the previous version is archived here.
    """
    __tablename__ = "policy_versions"
    
    id = Column(String(36), primary_key=True)
    policy_id = Column(String(36), ForeignKey("policies.id"), nullable=False)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    
    version_number = Column(Integer, nullable=False)
    rules = Column(JSON, nullable=False)
    
    # Who made this change?
    modified_by = Column(String(256), nullable=True)
    modified_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Change reason/notes
    change_reason = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<PolicyVersion {self.policy_id} v{self.version_number}>"
