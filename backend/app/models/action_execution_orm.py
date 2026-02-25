"""
Action Execution ORM for autonomous actions (P5.3)
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, Enum, Boolean
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum

from backend.app.core.database import Base


class ActionState(PyEnum):
    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ActionExecutionORM(Base):
    __tablename__ = "action_executions"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    action_type = Column(String(64), nullable=False)
    entity_id = Column(String(64), nullable=False)
    parameters = Column(JSON, nullable=True)
    affected_entity_count = Column(Integer, default=1)
    state = Column(Enum(ActionState), default=ActionState.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by = Column(String(256), nullable=True)
    executed_by = Column(String(256), nullable=True)
    trace_id = Column(String(128), nullable=True)
    result = Column(JSON, nullable=True)
    success = Column(Boolean, default=False)

    def __repr__(self):
        return f"<ActionExecution {self.id} {self.action_type} state={self.state}>"
