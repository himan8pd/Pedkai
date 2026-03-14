"""SITREP cross-team escalation routing service.

Routes SITREPs to appropriate teams based on domain, severity, and tenant config.
Supports: NOC Engineer, NOC Manager, Field Team, Vendor Support, Executive.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EscalationTier(str, Enum):
    NOC_ENGINEER = "noc_engineer"      # Tier 1 — first responder
    NOC_MANAGER = "noc_manager"        # Tier 2 — if unresolved 30 min
    FIELD_TEAM = "field_team"          # Tier 3 — physical investigation needed
    VENDOR_SUPPORT = "vendor_support"  # Tier 3 — equipment fault suspected
    EXECUTIVE = "executive"            # Tier 4 — major outage affecting SLA


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EscalationRule:
    domain: str                        # "RAN", "Core", "Transport", "BSS", "*" (all)
    severity: SeverityLevel
    initial_tier: EscalationTier
    escalation_after_minutes: int      # Escalate if unresolved after this
    escalate_to: EscalationTier
    requires_field: bool = False       # Flag for physical investigation


@dataclass
class RoutingDecision:
    sitrep_id: str
    entity_id: str
    domain: str
    severity: SeverityLevel
    assigned_tier: EscalationTier
    assigned_team_ids: list[str]
    escalation_rule: Optional[EscalationRule]
    rationale: str


class SitrepRouter:
    """Routes SITREPs to the correct team based on domain and severity."""

    DEFAULT_RULES: list[EscalationRule] = [
        EscalationRule("RAN", SeverityLevel.CRITICAL, EscalationTier.NOC_ENGINEER, 15, EscalationTier.NOC_MANAGER),
        EscalationRule("RAN", SeverityLevel.HIGH, EscalationTier.NOC_ENGINEER, 30, EscalationTier.NOC_MANAGER),
        EscalationRule("RAN", SeverityLevel.MEDIUM, EscalationTier.NOC_ENGINEER, 60, EscalationTier.FIELD_TEAM),
        EscalationRule("Core", SeverityLevel.CRITICAL, EscalationTier.NOC_MANAGER, 10, EscalationTier.EXECUTIVE),
        EscalationRule("Core", SeverityLevel.HIGH, EscalationTier.NOC_ENGINEER, 20, EscalationTier.NOC_MANAGER),
        EscalationRule("Transport", SeverityLevel.CRITICAL, EscalationTier.NOC_ENGINEER, 15, EscalationTier.FIELD_TEAM, requires_field=True),
        EscalationRule("Transport", SeverityLevel.HIGH, EscalationTier.NOC_ENGINEER, 30, EscalationTier.FIELD_TEAM, requires_field=True),
        EscalationRule("*", SeverityLevel.LOW, EscalationTier.NOC_ENGINEER, 120, EscalationTier.NOC_ENGINEER),
    ]

    def __init__(self, rules: list[EscalationRule] = None):
        self.rules = rules if rules is not None else self.DEFAULT_RULES

    def _find_rule(self, domain: str, severity: SeverityLevel) -> Optional[EscalationRule]:
        """Find the best matching rule for a domain+severity pair.

        Exact domain match takes priority over wildcard "*".
        """
        exact_match: Optional[EscalationRule] = None
        wildcard_match: Optional[EscalationRule] = None

        for rule in self.rules:
            if rule.severity != severity:
                continue
            if rule.domain == domain:
                exact_match = rule
                break
            if rule.domain == "*":
                wildcard_match = rule

        return exact_match or wildcard_match

    def route(
        self,
        sitrep_id: str,
        entity_id: str,
        domain: str,
        severity: SeverityLevel,
    ) -> RoutingDecision:
        """Find the best matching rule and return a RoutingDecision."""
        rule = self._find_rule(domain, severity)

        if rule is None:
            # Fallback: default to NOC_ENGINEER with no escalation rule
            logger.warning(
                "No escalation rule found for domain=%s severity=%s; defaulting to NOC_ENGINEER",
                domain,
                severity,
            )
            return RoutingDecision(
                sitrep_id=sitrep_id,
                entity_id=entity_id,
                domain=domain,
                severity=severity,
                assigned_tier=EscalationTier.NOC_ENGINEER,
                assigned_team_ids=[EscalationTier.NOC_ENGINEER.value],
                escalation_rule=None,
                rationale=f"No specific rule for domain={domain} severity={severity.value}; defaulting to NOC_ENGINEER.",
            )

        field_note = " Physical investigation required." if rule.requires_field else ""
        rationale = (
            f"Domain={domain}, Severity={severity.value}: assigned to {rule.initial_tier.value}."
            f" Escalate to {rule.escalate_to.value} after {rule.escalation_after_minutes} min if unresolved.{field_note}"
        )

        logger.info("SITREP %s routed: %s", sitrep_id, rationale)

        return RoutingDecision(
            sitrep_id=sitrep_id,
            entity_id=entity_id,
            domain=domain,
            severity=severity,
            assigned_tier=rule.initial_tier,
            assigned_team_ids=[rule.initial_tier.value],
            escalation_rule=rule,
            rationale=rationale,
        )

    def get_escalation_path(self, domain: str, severity: SeverityLevel) -> list[EscalationTier]:
        """Return ordered escalation path for a domain+severity combination.

        Returns [initial_tier, escalate_to] when a rule exists, or just
        [initial_tier] when initial_tier == escalate_to (no progression).
        Falls back to [NOC_ENGINEER] when no rule is found.
        """
        rule = self._find_rule(domain, severity)
        if rule is None:
            return [EscalationTier.NOC_ENGINEER]

        if rule.initial_tier == rule.escalate_to:
            return [rule.initial_tier]

        return [rule.initial_tier, rule.escalate_to]

    def should_escalate(self, rule: EscalationRule, elapsed_minutes: int) -> bool:
        """Check if elapsed time exceeds escalation threshold."""
        return elapsed_minutes >= rule.escalation_after_minutes

    def get_field_required_domains(self) -> list[str]:
        """Return domains that require field team for any severity."""
        domains: list[str] = []
        for rule in self.rules:
            if rule.requires_field and rule.domain not in domains:
                domains.append(rule.domain)
        return domains


def get_sitrep_router(rules: list[EscalationRule] = None) -> SitrepRouter:
    return SitrepRouter(rules=rules)
