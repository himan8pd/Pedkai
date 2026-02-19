import yaml
import logging
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel
from simpleeval import simple_eval

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

class PolicyEngine:
    """
    Pedkai Policy Engine - Enforces the "Telco Constitution".
    Finding C-1 FIX: Replaced insecure eval() with simpleeval.
    Finding M-2 FIX: Handled ALLOW action.
    Finding M-3 FIX: Uses absolute path logic.
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

# Global Instance
policy_engine = PolicyEngine()
