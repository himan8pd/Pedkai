"""
Safety Gate Service — 7 gates for autonomous action execution.

Product Spec §7 Level 3: All 7 gates must PASS for an action to be approved.
Any single FAIL blocks execution.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class GateResult:
    gate_name: str
    status: GateStatus
    reason: str
    metadata: dict = field(default_factory=dict)


@dataclass
class SafetyDecision:
    action_id: str
    approved: bool
    gates_passed: int
    gates_failed: int
    results: list

    def summary(self) -> str:
        return (
            f"{self.gates_passed}/7 gates passed — "
            f"{'APPROVED' if self.approved else 'BLOCKED'}"
        )


class SafetyGateService:
    """7 safety gates for autonomous action execution per product spec §7 Level 3."""

    def gate_1_blast_radius(self, action: dict) -> GateResult:
        """Gate 1: Blast radius check. Block if affected_entities > 10."""
        affected = action.get("affected_entities", [])
        count = len(affected) if isinstance(affected, list) else int(affected)
        if count > 10:
            return GateResult(
                "blast_radius",
                GateStatus.FAIL,
                f"Affected entities {count} exceeds limit 10",
            )
        return GateResult(
            "blast_radius",
            GateStatus.PASS,
            f"{count} entities within limit",
        )

    def gate_2_policy_rules(self, action: dict, tenant_id: str) -> GateResult:
        """Gate 2: Policy rules check. Action type must be in allowed_action_types."""
        allowed = action.get("allowed_action_types", ["acknowledge", "create_ticket"])
        action_type = action.get("action_type", "")
        if action_type not in allowed:
            return GateResult(
                "policy_rules",
                GateStatus.FAIL,
                f"Action '{action_type}' not in allowed types",
            )
        return GateResult(
            "policy_rules",
            GateStatus.PASS,
            f"Action '{action_type}' allowed",
        )

    def gate_3_confidence_threshold(self, action: dict) -> GateResult:
        """Gate 3: Confidence threshold. Block if confidence < 0.85."""
        confidence = action.get("confidence", 0.0)
        if confidence < 0.85:
            return GateResult(
                "confidence_threshold",
                GateStatus.FAIL,
                f"Confidence {confidence:.2f} < 0.85",
            )
        return GateResult(
            "confidence_threshold",
            GateStatus.PASS,
            f"Confidence {confidence:.2f} sufficient",
        )

    def gate_4_maintenance_window(self, action: dict) -> GateResult:
        """Gate 4: No action during maintenance windows. Check ghost_masked flag."""
        if action.get("ghost_masked", False):
            return GateResult(
                "maintenance_window",
                GateStatus.FAIL,
                "Entity is in maintenance window (ghost masked)",
            )
        return GateResult(
            "maintenance_window",
            GateStatus.PASS,
            "No active maintenance window",
        )

    def gate_5_duplicate_suppression(self, action: dict) -> GateResult:
        """Gate 5: Suppress duplicate actions. Block if same action executed in last 3600s."""
        last_executed = action.get("last_executed_seconds_ago", None)
        if last_executed is not None and last_executed < 3600:
            return GateResult(
                "duplicate_suppression",
                GateStatus.FAIL,
                f"Duplicate: same action {last_executed}s ago",
            )
        return GateResult(
            "duplicate_suppression",
            GateStatus.PASS,
            "No recent duplicate action",
        )

    def gate_6_human_gate(self, action: dict) -> GateResult:
        """Gate 6: High-risk actions require human approval.
        If action.risk_level == 'HIGH', require human_approved=True."""
        risk = action.get("risk_level", "LOW")
        if risk == "HIGH" and not action.get("human_approved", False):
            return GateResult(
                "human_gate",
                GateStatus.FAIL,
                "HIGH risk action requires human approval",
            )
        return GateResult(
            "human_gate",
            GateStatus.PASS,
            f"Risk level {risk} cleared",
        )

    def gate_7_rate_limit(self, action: dict) -> GateResult:
        """Gate 7: Rate limit — max 20 autonomous actions per hour per tenant."""
        actions_this_hour = action.get("actions_this_hour", 0)
        if actions_this_hour >= 20:
            return GateResult(
                "rate_limit",
                GateStatus.FAIL,
                f"{actions_this_hour} actions this hour >= limit 20",
            )
        return GateResult(
            "rate_limit",
            GateStatus.PASS,
            f"{actions_this_hour}/20 actions this hour",
        )

    def evaluate(self, action: dict, tenant_id: str = "default") -> SafetyDecision:
        """Run all 7 gates. Return SafetyDecision — approved only if all gates PASS."""
        results = [
            self.gate_1_blast_radius(action),
            self.gate_2_policy_rules(action, tenant_id),
            self.gate_3_confidence_threshold(action),
            self.gate_4_maintenance_window(action),
            self.gate_5_duplicate_suppression(action),
            self.gate_6_human_gate(action),
            self.gate_7_rate_limit(action),
        ]
        passed = sum(1 for r in results if r.status == GateStatus.PASS)
        failed = sum(1 for r in results if r.status == GateStatus.FAIL)
        return SafetyDecision(
            action_id=action.get("action_id", "unknown"),
            approved=failed == 0,
            gates_passed=passed,
            gates_failed=failed,
            results=results,
        )
