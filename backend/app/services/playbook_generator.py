"""Automated playbook generator from high-confidence Decision Memory patterns.

Generates reusable NOC runbooks when Pedk.ai has resolved similar fault patterns
with confidence >= 0.9 at least 3 times.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
import os
import uuid

logger = logging.getLogger(__name__)


@dataclass
class PlaybookStep:
    step_number: int
    action: str
    expected_outcome: str
    rollback: Optional[str] = None
    automated: bool = False  # Can Pedk.ai perform this automatically?


@dataclass
class Playbook:
    playbook_id: str
    title: str
    fault_pattern: str        # e.g., "sleeping_cell_prb_degradation"
    domain: str               # "RAN", "Core", "Transport"
    confidence: float         # Aggregate confidence across source decisions
    source_decision_ids: list[str]
    steps: list[PlaybookStep]
    created_at: datetime
    times_applied: int = 0
    last_applied: Optional[datetime] = None

    def to_markdown(self) -> str:
        """Render playbook as a formatted markdown runbook."""
        lines = [
            f"# Playbook: {self.title}",
            f"",
            f"**Playbook ID:** {self.playbook_id}",
            f"**Domain:** {self.domain}",
            f"**Fault Pattern:** {self.fault_pattern}",
            f"**AI Confidence:** {self.confidence:.0%}",
            f"**Generated from:** {len(self.source_decision_ids)} resolved incidents",
            f"**Last Updated:** {self.created_at.strftime('%Y-%m-%d')}",
            f"",
            f"## Steps",
        ]
        for step in self.steps:
            auto_tag = " *(Pedk.ai automated)*" if step.automated else ""
            lines.append(f"\n### Step {step.step_number}: {step.action}{auto_tag}")
            lines.append(f"**Expected outcome:** {step.expected_outcome}")
            if step.rollback:
                lines.append(f"**Rollback:** {step.rollback}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialise the playbook to a plain dict."""
        return {
            "playbook_id": self.playbook_id,
            "title": self.title,
            "fault_pattern": self.fault_pattern,
            "domain": self.domain,
            "confidence": self.confidence,
            "source_decision_ids": list(self.source_decision_ids),
            "steps": [
                {
                    "step_number": s.step_number,
                    "action": s.action,
                    "expected_outcome": s.expected_outcome,
                    "rollback": s.rollback,
                    "automated": s.automated,
                }
                for s in self.steps
            ],
            "created_at": self.created_at.isoformat(),
            "times_applied": self.times_applied,
            "last_applied": self.last_applied.isoformat() if self.last_applied else None,
        }


# ---------------------------------------------------------------------------
# Generic fallback steps used when no template matches the fault pattern.
# ---------------------------------------------------------------------------
_GENERIC_STEPS = [
    PlaybookStep(1, "Review Pedk.ai SITREP for fault summary", "Fault details confirmed in SITREP"),
    PlaybookStep(2, "Identify affected entities in CMDB", "Affected network elements listed"),
    PlaybookStep(3, "Isolate root cause via Dark Graph analysis", "Root-cause node identified"),
    PlaybookStep(4, "Apply remediation action per vendor guidance", "Service restored", rollback="Escalate to vendor if action fails"),
    PlaybookStep(5, "Monitor KPIs for 30 minutes post-action", "KPIs return to baseline", automated=True),
]


class PlaybookGenerator:
    """Generates playbooks from Decision Memory patterns."""

    MIN_OCCURRENCES = 3       # Minimum resolved incidents to generate playbook
    MIN_CONFIDENCE = 0.9      # Minimum confidence threshold

    PATTERN_TEMPLATES: dict = {
        "sleeping_cell": {
            "title": "Sleeping Cell Recovery Procedure",
            "domain": "RAN",
            "steps": [
                PlaybookStep(1, "Verify sleeping cell detection via Pedk.ai SITREP", "SITREP confirms PRB < 5%, SINR degraded, handover < 80%"),
                PlaybookStep(2, "Check CMDB for recent planned maintenance", "No maintenance found for this cell"),
                PlaybookStep(3, "Review neighbouring cell load", "Confirm traffic has not migrated to neighbours"),
                PlaybookStep(4, "Initiate cell reset via element manager", "Cell returns to active state within 5 minutes", rollback="Escalate to vendor if reset fails"),
                PlaybookStep(5, "Monitor KPIs for 30 minutes post-reset", "PRB normalises to baseline ± 20%", automated=True),
            ],
        },
        "transport_degradation": {
            "title": "Transport Link Degradation Response",
            "domain": "Transport",
            "steps": [
                PlaybookStep(1, "Identify affected transport segment from Dark Graph", "Degraded link identified between hub and RAN nodes"),
                PlaybookStep(2, "Check transport equipment alarms", "Physical layer alarm or BER degradation"),
                PlaybookStep(3, "Dispatch field team if physical fault suspected", "Field team dispatched"),
                PlaybookStep(4, "Activate backup path if available", "Traffic rerouted, throughput restored", rollback="Contact transport vendor if no backup available"),
                PlaybookStep(5, "Update CMDB with link status", "CMDB reflects degraded link", automated=True),
            ],
        },
        "cmdb_divergence": {
            "title": "CMDB Divergence Remediation",
            "domain": "ALL",
            "steps": [
                PlaybookStep(1, "Review Dark Graph divergence report", "List of dark nodes, phantom nodes, and mutations identified"),
                PlaybookStep(2, "Validate dark nodes via field confirmation or active probe", "Dark nodes confirmed or disproved"),
                PlaybookStep(3, "Update CMDB for confirmed dark nodes", "CMDB updated with discovered entities"),
                PlaybookStep(4, "Retire phantom nodes from CMDB", "Phantom entries removed after physical verification"),
                PlaybookStep(5, "Document identity mutations for vendor escalation", "Mutation root cause identified"),
            ],
        },
    }

    # ------------------------------------------------------------------
    # Internal helper: resolve a template key from a free-form fault pattern
    # ------------------------------------------------------------------
    def _match_template_key(self, fault_pattern: str) -> Optional[str]:
        """Return the PATTERN_TEMPLATES key that best matches fault_pattern, or None."""
        lp = fault_pattern.lower()
        for key in self.PATTERN_TEMPLATES:
            if key in lp or lp in key:
                return key
        return None

    # ------------------------------------------------------------------
    # Public async API (db_session is optional so unit tests can call
    # without a real database connection)
    # ------------------------------------------------------------------

    async def find_eligible_patterns(self, tenant_id: str, db_session) -> list[dict]:
        """Query DecisionTraceORM for fault patterns with >= MIN_OCCURRENCES
        resolved incidents at confidence >= MIN_CONFIDENCE.

        Returns list of {fault_pattern, count, avg_confidence, decision_ids}.

        When db_session is None the method returns an empty list (safe for
        unit tests that do not wire up a database).
        """
        if db_session is None:
            return []

        from sqlalchemy import select, func, and_
        from backend.app.models.decision_trace_orm import DecisionTraceORM

        try:
            # Group by the first tag (used as fault pattern) or trigger_type
            stmt = (
                select(
                    DecisionTraceORM.trigger_type.label("fault_pattern"),
                    func.count(DecisionTraceORM.id).label("count"),
                    func.avg(DecisionTraceORM.confidence_score).label("avg_confidence"),
                    func.array_agg(DecisionTraceORM.id.cast(str)).label("decision_ids"),
                )
                .where(
                    and_(
                        DecisionTraceORM.tenant_id == tenant_id,
                        DecisionTraceORM.status == "cleared",
                        DecisionTraceORM.confidence_score >= self.MIN_CONFIDENCE,
                    )
                )
                .group_by(DecisionTraceORM.trigger_type)
                .having(func.count(DecisionTraceORM.id) >= self.MIN_OCCURRENCES)
            )
            result = await db_session.execute(stmt)
            rows = result.fetchall()
            return [
                {
                    "fault_pattern": row.fault_pattern,
                    "count": row.count,
                    "avg_confidence": float(row.avg_confidence),
                    "decision_ids": list(row.decision_ids),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("find_eligible_patterns query failed: %s", exc)
            return []

    async def generate_playbook(self, pattern: dict, tenant_id: str) -> "Playbook":
        """Generate a Playbook from a pattern dict.

        Uses PATTERN_TEMPLATES if pattern matches a known fault type.
        Falls back to generic steps for unknown patterns.
        """
        fault_pattern: str = pattern.get("fault_pattern", "unknown")
        avg_confidence: float = float(pattern.get("avg_confidence", 0.0))
        decision_ids: list[str] = list(pattern.get("decision_ids", []))

        template_key = self._match_template_key(fault_pattern)

        if template_key is not None:
            tmpl = self.PATTERN_TEMPLATES[template_key]
            title = tmpl["title"]
            domain = tmpl["domain"]
            steps = list(tmpl["steps"])
        else:
            title = f"Generic Fault Response: {fault_pattern.replace('_', ' ').title()}"
            domain = "ALL"
            steps = list(_GENERIC_STEPS)

        return Playbook(
            playbook_id=str(uuid.uuid4()),
            title=title,
            fault_pattern=fault_pattern,
            domain=domain,
            confidence=avg_confidence,
            source_decision_ids=decision_ids,
            steps=steps,
            created_at=datetime.utcnow(),
        )

    async def export_playbooks_to_markdown(
        self,
        tenant_id: str,
        output_dir: str,
        db_session=None,
    ) -> list[str]:
        """Find eligible patterns, generate playbooks, write to output_dir/*.md.

        Returns list of filenames created.
        """
        os.makedirs(output_dir, exist_ok=True)

        patterns = await self.find_eligible_patterns(tenant_id, db_session)
        created_files: list[str] = []

        for pattern in patterns:
            playbook = await self.generate_playbook(pattern, tenant_id)
            safe_name = playbook.fault_pattern.replace(" ", "_").replace("/", "-")
            filename = os.path.join(output_dir, f"{safe_name}.md")
            with open(filename, "w", encoding="utf-8") as fh:
                fh.write(playbook.to_markdown())
            created_files.append(filename)
            logger.info("Exported playbook: %s", filename)

        return created_files

    async def get_playbook_by_fault_pattern(self, fault_pattern: str) -> Optional[Playbook]:
        """Return a Playbook for a known fault pattern, or None."""
        template_key = self._match_template_key(fault_pattern)
        if template_key is None:
            return None

        tmpl = self.PATTERN_TEMPLATES[template_key]
        return Playbook(
            playbook_id=str(uuid.uuid4()),
            title=tmpl["title"],
            fault_pattern=fault_pattern,
            domain=tmpl["domain"],
            confidence=self.MIN_CONFIDENCE,
            source_decision_ids=[],
            steps=list(tmpl["steps"]),
            created_at=datetime.utcnow(),
        )


def get_playbook_generator() -> PlaybookGenerator:
    return PlaybookGenerator()
