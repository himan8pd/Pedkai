import yaml
import logging
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel
from simpleeval import simple_eval
from datetime import datetime
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Configure logging
logger = logging.getLogger(__name__)

class Policy(BaseModel):
    id: str
    name: str
    description: str
    priority: int
    condition: str
    action: str
    overrides: Optional[List[str]] = None
    constraints: Optional[List[str]] = None
    parameters: Optional[Dict[str, Any]] = None

class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    applied_policies: List[str]
    required_actions: List[str]

class ActionDecision(BaseModel):
    """Decision from autonomous action policy evaluation (v2)"""
    decision: str  # "allow", "deny", "confirm"
    confidence: float
    matched_rules: Dict[str, Dict[str, Any]]
    reason: str
    trace_id: Optional[str] = None
    recommended_confirmation_window_sec: int = 30

class PolicyEngine:
    """
    Pedkai Policy Engine - Enforces the "Telco Constitution".
    Finding C-1 FIX: Replaced insecure eval() with simpleeval.
    Finding M-2 FIX: Handled ALLOW action.
    Finding M-3 FIX: Uses absolute path logic.
    P5.1 ENHANCEMENT: Added v2 support for autonomous action evaluation with versioning and audit trail.
    """
    def __init__(self, policy_path: Optional[str] = None):
        if policy_path:
            self.policy_path = Path(policy_path)
        else:
            # Finding H-8 FIX: Secure Path Prioritization
            # Priority 1: Secure read-only mount (e.g., K8s Secret/ConfigMap)
            # Priority 2: Absolute path relative to source (Fallback)
            secure_path = Path("/etc/pedkai/policies/global_policies.yaml")
            # Finding H-8: Robust absolute pathing
            base_dir = Path(__file__).parent.parent
            local_path = base_dir / "policies" / "global_policies.yaml"
            
            if secure_path.exists():
                self.policy_path = secure_path
                logger.info(f"Policy Engine: Using secure production path: {self.policy_path}")
            else:
                # Finding H-8: Always prioritize the secure mount in prod
                logger.warning(f"Policy Engine: Falling back to local development path: {local_path.absolute()}")
                self.policy_path = local_path
            
        self.policies: List[Policy] = []
        self.load_policies()

    def _verify_integrity(self, content: bytes) -> bool:
        """Finding H-8: Optional checksum verification for production deployments."""
        import hashlib
        expected_hash = os.getenv("PEDKAI_POLICY_CHECKSUM")
        if not expected_hash:
            return True # Not enforced
            
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            logger.critical(f"POLICY INTEGRITY BREACH: Found {actual_hash}, expected {expected_hash}")
            return False
        return True

    def load_policies(self):
        """Loads and parses the YAML policy file."""
        if not self.policy_path.exists():
            logger.error(f"Policy file not found: {self.policy_path}")
            return

        try:
            with open(self.policy_path, "rb") as f:
                content = f.read()
                
            if not self._verify_integrity(content):
                raise PermissionError("Policy integrity check failed. Refusing to load Constitution.")

            data = yaml.safe_load(content)
            self.version = data.get("version", "1.0.0")
            self.parameters = data.get("parameters", {})
            self.policies = [Policy(**p) for p in data.get("policies", [])]
            # Sort by priority (highest first)
            self.policies.sort(key=lambda x: x.priority, reverse=True)
            logger.info(f"Loaded {len(self.policies)} policies (Version: {self.version}) and {len(self.parameters)} parameters from {self.policy_path}")
        except PermissionError:
            raise
        except Exception as e:
            logger.error(f"Failed to load policies: {e}")

    def get_parameter(self, key: str, default: Any = None) -> Any:
        """Retrieves a global operational parameter."""
        return self.parameters.get(key, default)

    def is_emergency_service(self, context: Dict[str, Any]) -> bool:
        """Check if the context relates to an emergency service entity."""
        return (
            context.get("entity_type") == "EMERGENCY_SERVICE"
            or context.get("is_emergency_service") is True
        )

    def evaluate(self, context: Dict[str, Any]) -> PolicyDecision:
        """
        Evaluates the current context against all active policies.
        Finding C-1: Uses simple_eval for safe condition checking.
        """
        # H&S §2.13: Emergency service protection — hardcoded, cannot be overridden
        if self.is_emergency_service(context):
            return PolicyDecision(
                allowed=True,
                reason="EMERGENCY SERVICE — unconditional P1. This policy cannot be overridden.",
                applied_policies=["EMERGENCY_SERVICE_P1_HARDCODE"],
                required_actions=["UNCONDITIONAL_P1"]
            )

        applied_policies = []
        required_actions = []
        
        # Default decision is ALLOW unless restricted
        decision_allowed = True
        decision_reason = "No restrictive policies matched."

        for policy in self.policies:
            try:
                # Finding C-1: Safe logic evaluation using simple_eval
                if simple_eval(policy.condition, names=context):
                    logger.info(f"Policy Matched: {policy.name} ({policy.id})")
                    applied_policies.append(policy.name)
                    
                    if policy.action == "REQUIRE_APPROVAL":
                        decision_allowed = False
                        decision_reason = f"Blocked by policy: {policy.name}"
                        required_actions.append("HUMAN_APPROVAL")
                    elif policy.action == "THROTTLE":
                        limit = policy.parameters.get("throttle_limit", "1Mbps") if policy.parameters else "1Mbps"
                        required_actions.append(f"APPLY_THROTTLE:{limit}")
                    elif policy.action == "PRIORITIZE":
                        required_actions.append("PRIORITIZE_TRAFFIC")
                    elif policy.action == "ALLOW":
                        # Finding M-2: If a high-priority policy explicitly ALLOWs,
                        # and we haven't been blocked yet, we can confirm allowance.
                        if decision_allowed:
                            return PolicyDecision(
                                allowed=True,
                                reason=f"Explicitly allowed by high-priority policy: {policy.name}",
                                applied_policies=applied_policies,
                                required_actions=required_actions if required_actions else ["MONITOR_ONLY"]
                            )
            except Exception as e:
                logger.warning(f"Error evaluating policy {policy.id}: {e}")

        return PolicyDecision(
            allowed=decision_allowed,
            reason=decision_reason,
            applied_policies=applied_policies,
            required_actions=required_actions if required_actions else ["MONITOR_ONLY"]
        )

    # ══════════════════════════════════════════════════════════════════════════════════
    # P5.1 ENHANCEMENT: v2 Autonomous Action Evaluation with Audit Trail
    # ══════════════════════════════════════════════════════════════════════════════════

    async def evaluate_autonomous_action(
        self,
        session: AsyncSession,
        tenant_id: str,
        action_type: str,
        entity_id: str,
        affected_entity_count: int,
        action_parameters: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        confidence_score: Optional[float] = None,
    ) -> ActionDecision:
        """
        P5.1: Evaluate if an autonomous action is permitted.
        
        Implements the Policy Gate in the safety rails pipeline.
        Returns detailed decision with matched/failed rules for audit trail.
        
        Args:
            session: Database session for storing audit trail
            tenant_id: Tenant requesting the action
            action_type: Type of action (cell_failover, connection_throttle, etc.)
            entity_id: Primary entity being modified
            affected_entity_count: Total entities that would be affected
            action_parameters: Optional action-specific parameters
            trace_id: Distributed trace ID for linking to requests
            confidence_score: Similarity/confidence from Decision Memory (0.0-1.0)
        
        Returns:
            ActionDecision with decision, confidence, matched rules, and reason
        """
        try:
            # Fetch tenant's active policy from database
            from backend.app.models.policy_orm import PolicyORM
            
            stmt = select(PolicyORM).where(
                (PolicyORM.tenant_id == tenant_id) &
                (PolicyORM.status == "active")
            ).order_by(PolicyORM.updated_at.desc()).limit(1)
            
            result = await session.execute(stmt)
            policy_orm = result.scalar_one_or_none()
            
            # Use defaults if no policy defined
            if not policy_orm:
                rules = {
                    "allowed_actions": ["cell_failover", "connection_throttle", "alarm_silence"],
                    "blast_radius_limit": 100,
                    "confidence_threshold": 0.85,
                    "min_success_rate": 0.90,
                    "auto_rollback_threshold_pct": 10.0,
                    "allowed_entity_types": ["CELL", "SECTOR"]
                }
                logger.info(f"No policy for tenant {tenant_id}, using defaults")
            else:
                rules = policy_orm.rules or {}
            
            # Evaluate each gate
            matched_rules = {}
            all_passed = True
            
            # Gate 1: Action type allowed?
            allowed_actions = rules.get("allowed_actions", ["cell_failover"])
            gate1_passed = action_type in allowed_actions
            matched_rules["action_type_check"] = {
                "passed": gate1_passed,
                "action_type": action_type,
                "allowed_actions": allowed_actions
            }
            all_passed = all_passed and gate1_passed
            
            # Gate 2: Blast radius within limit?
            blast_radius_limit = rules.get("blast_radius_limit", 100)
            gate2_passed = affected_entity_count <= blast_radius_limit
            matched_rules["blast_radius_check"] = {
                "passed": gate2_passed,
                "entities_affected": affected_entity_count,
                "limit": blast_radius_limit
            }
            all_passed = all_passed and gate2_passed
            
            # Gate 3: Confidence threshold met?
            confidence_threshold = rules.get("confidence_threshold", 0.85)
            confidence = confidence_score or 0.0
            gate3_passed = confidence >= confidence_threshold
            matched_rules["confidence_threshold_check"] = {
                "passed": gate3_passed,
                "required": confidence_threshold,
                "actual": confidence
            }
            all_passed = all_passed and gate3_passed
            
            # Determine decision
            decision = "allow" if all_passed else "deny"
            final_confidence = confidence if all_passed else confidence * 0.5
            reason = (
                f"All gates passed: action approved"
                if all_passed
                else f"Policy gate(s) failed: {[k for k, v in matched_rules.items() if not v.get('passed')]}"
            )
            
            # Store evaluation in audit trail
            from backend.app.models.policy_orm import PolicyEvaluationORM
            
            evaluation = PolicyEvaluationORM(
                id=str(uuid.uuid4()),
                policy_id=policy_orm.id if policy_orm else "default",
                tenant_id=tenant_id,
                action_type=action_type,
                action_parameters=action_parameters,
                decision=decision,
                confidence=final_confidence,
                matched_rules=matched_rules,
                trace_id=trace_id,
                evaluated_by="autonomous-executor",
                evaluated_at=datetime.utcnow()
            )
            session.add(evaluation)
            await session.flush()
            
            logger.info(
                f"Policy evaluation: tenant={tenant_id}, action={action_type}, "
                f"decision={decision}, confidence={final_confidence:.2f}"
            )
            
            return ActionDecision(
                decision=decision,
                confidence=final_confidence,
                matched_rules=matched_rules,
                reason=reason,
                trace_id=trace_id,
                recommended_confirmation_window_sec=rules.get("confirmation_window_sec", 30)
            )
        
        except Exception as e:
            logger.error(f"Error evaluating autonomous action: {e}", exc_info=True)
            # Fail-safe: deny on error
            return ActionDecision(
                decision="deny",
                confidence=0.0,
                matched_rules={},
                reason=f"Policy evaluation error: {str(e)}",
                trace_id=trace_id
            )

# Global Cache for Singleton
_policy_engine: Optional[PolicyEngine] = None

def get_policy_engine() -> PolicyEngine:
    """
    Factory function to get a PolicyEngine instance.
    Ensures a single instance is used across the application.
    """
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine
