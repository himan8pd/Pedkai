"""
Policy Schemas (P5.1)

Pydantic models for Policy API requests/responses.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class ActionDecisionEnum(str, Enum):
    """Decision outcomes for policy evaluation"""
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class PolicyRules(BaseModel):
    """Policy rule constraints for autonomous actions"""
    allowed_actions: List[str] = Field(
        default=["cell_failover", "connection_throttle", "alarm_silence"],
        description="Action types this policy permits"
    )
    blast_radius_limit: int = Field(default=100, description="Max entities affected by single action")
    confidence_threshold: float = Field(default=0.85, description="Min similarity score (0.0-1.0)")
    min_success_rate: float = Field(default=0.90, description="Min historical success rate")
    confirmation_window_sec: int = Field(default=30, description="Seconds before auto-execute")
    auto_rollback_threshold_pct: float = Field(default=10.0, description="Trigger rollback if KPI degrades >X%")
    allowed_entity_types: List[str] = Field(default=["CELL", "SECTOR"], description="Target entity types")
    restricted_vendors: List[str] = Field(default=[], description="Vendors to exclude from autonomy")


class PolicyCreate(BaseModel):
    """Request to create a new policy"""
    name: str = Field(..., description="Policy name (e.g., 'cell_failover_tier1')")
    description: Optional[str] = None
    rules: PolicyRules
    created_by: Optional[str] = None


class PolicyUpdate(BaseModel):
    """Request to update an existing policy"""
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[PolicyRules] = None
    status: Optional[str] = None  # active, archived, draft
    modified_by: Optional[str] = None
    change_reason: Optional[str] = None


class PolicyResponse(BaseModel):
    """Response containing policy details"""
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    version: int
    status: str
    rules: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    
    class Config:
        from_attributes = True


class PolicyEvaluationRule(BaseModel):
    """Details of a single rule evaluation"""
    passed: bool
    rule_name: str
    actual_value: Any = None
    required_value: Any = None
    details: Optional[str] = None


class PolicyEvaluationRequest(BaseModel):
    """Request to pre-evaluate action compliance"""
    action_type: str
    entity_id: str
    action_parameters: Optional[Dict[str, Any]] = None
    affected_entity_count: Optional[int] = None


class PolicyEvaluationResponse(BaseModel):
    """Response from policy evaluation"""
    decision: ActionDecisionEnum
    confidence: float
    matched_rules: Dict[str, Dict[str, Any]]  # Rule name -> evaluation details
    reason: str
    trace_id: Optional[str] = None
    recommended_confirmation_window_sec: int = 30
    
    class Config:
        from_attributes = True


class PolicyAuditEntry(BaseModel):
    """Single entry in policy evaluation audit trail"""
    id: str
    policy_id: str
    action_type: str
    decision: ActionDecisionEnum
    confidence: float
    evaluated_at: datetime
    evaluated_by: Optional[str]
    matched_rules: Dict[str, Any]
    trace_id: Optional[str]
    
    class Config:
        from_attributes = True


class PolicyVersionResponse(BaseModel):
    """Historical policy version"""
    version_number: int
    rules: Dict[str, Any]
    modified_by: Optional[str]
    modified_at: datetime
    change_reason: Optional[str]
    
    class Config:
        from_attributes = True
