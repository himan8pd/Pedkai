"""
LLM-augmented enrichment for divergence analysis.

Builds structured prompts from rule-based enrichment data and calls the
on-prem LLM (Ollama / TSLAM) to generate natural-language analysis.
Gracefully degrades to None if the LLM is unavailable.

Used by: GET /divergence/enriched-profile/{result_id}  (reports.py)
"""

from typing import Any, Dict, Optional

from backend.app.core.logging import get_logger
from backend.app.services.llm_adapter import get_adapter

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt builders per divergence type
# ---------------------------------------------------------------------------

def _dark_node_prompt(enrichment: dict, target_id: str) -> str:
    parts = [
        "You are a telecom network intelligence analyst. Analyse this dark node — "
        "an entity found in operational telemetry but missing from the CMDB.\n",
        f"Entity ID: {target_id}",
        f"Inferred device type: {enrichment.get('inferred_device_type', 'UNKNOWN')} "
        f"(confidence: {enrichment.get('device_type_confidence', 0)})",
        f"Inferred role: {enrichment.get('inferred_role', 'Unknown')}",
        f"Domain: {enrichment.get('domain', 'N/A')}",
        f"RAT type: {enrichment.get('rat_type', 'N/A')}",
        f"Vendor hint: {enrichment.get('vendor_hint', 'N/A')}",
    ]

    obs = enrichment.get("observation_window", {})
    if obs:
        parts.append(
            f"Observation window: {obs.get('first_seen', '?')} to {obs.get('last_seen', '?')}, "
            f"{obs.get('total_samples', 0)} samples across {obs.get('distinct_kpis', 0)} KPIs"
        )

    kpis = enrichment.get("kpi_names", [])
    if kpis:
        parts.append(f"KPIs reported: {', '.join(kpis[:15])}")

    alarms = enrichment.get("alarm_profiles", [])
    if alarms:
        alarm_summary = "; ".join(
            f"{a['alarm_type']} ({a['severity']}, {a['count']}x)"
            for a in alarms[:5]
        )
        parts.append(f"Alarm profile: {alarm_summary}")

    topo = enrichment.get("topology_context", {})
    if topo.get("neighbour_count", 0) > 0:
        parts.append(f"Topology: {topo['neighbour_count']} neighbour relations")

    parts.append(
        "\nProvide a concise analysis covering:\n"
        "1. What this device most likely is and its operational significance\n"
        "2. Why it is missing from CMDB (probable root cause)\n"
        "3. Risk assessment if left unregistered\n"
        "4. Specific, prioritised remediation steps\n"
        "Keep the response under 300 words."
    )
    return "\n".join(parts)


def _phantom_node_prompt(enrichment: dict, target_id: str) -> str:
    return (
        "You are a telecom network intelligence analyst. Analyse this phantom node — "
        "an entity declared in CMDB but with zero operational telemetry.\n\n"
        f"Entity ID: {target_id}\n"
        f"Entity type: {enrichment.get('entity_type', 'N/A')}\n"
        f"Entity name: {enrichment.get('entity_name', 'N/A')}\n"
        f"Detection method: {enrichment.get('detection_method', 'signal_absence')}\n"
        f"Signals checked: {', '.join(enrichment.get('signals_checked', []))}\n"
        f"Confidence: {enrichment.get('confidence', 0)}\n\n"
        "Provide a concise analysis covering:\n"
        "1. Most likely reason this entity has no operational signals\n"
        "2. Whether this represents a decommissioned, misconfigured, or passive asset\n"
        "3. Risk assessment (revenue impact, compliance, operational blind spots)\n"
        "4. Prioritised remediation steps\n"
        "Keep the response under 250 words."
    )


def _dark_edge_prompt(enrichment: dict, target_id: str) -> str:
    nr = enrichment.get("neighbour_relation", {})
    return (
        "You are a telecom network intelligence analyst. Analyse this dark edge — "
        "an operational link found in telemetry but missing from CMDB topology.\n\n"
        f"Link: {nr.get('from_name', '?')} → {nr.get('to_name', '?')}\n"
        f"Neighbour type: {nr.get('neighbour_type', 'N/A')}\n"
        f"Handover attempts: {nr.get('handover_attempts', 'N/A')}\n"
        f"Handover success rate: {nr.get('handover_success_rate', 'N/A')}\n"
        f"Distance: {nr.get('distance_m', 'N/A')}m\n"
        f"Confidence: {enrichment.get('confidence', 0)}\n\n"
        "Provide a concise analysis covering:\n"
        "1. What this operational relationship indicates about network topology\n"
        "2. Why CMDB might be missing this link\n"
        "3. Impact of the CMDB gap on capacity planning and fault management\n"
        "4. Specific remediation steps\n"
        "Keep the response under 250 words."
    )


def _generic_prompt(enrichment: dict, div_type: str, target_id: str) -> str:
    reasoning = enrichment.get("reasoning", [])
    remediation = enrichment.get("remediation_options", [])
    return (
        f"You are a telecom network intelligence analyst. Analyse this {div_type.replace('_', ' ')} "
        f"divergence for entity {target_id}.\n\n"
        f"Existing reasoning:\n" + "\n".join(f"- {r}" for r in reasoning) + "\n\n"
        f"Suggested remediation:\n" + "\n".join(f"- {r}" for r in remediation) + "\n\n"
        f"Confidence: {enrichment.get('confidence', 0)}\n\n"
        "Provide a concise expert analysis: root cause assessment, risk level, "
        "and prioritised remediation. Keep under 200 words."
    )


_PROMPT_BUILDERS = {
    "dark_node": _dark_node_prompt,
    "phantom_node": _phantom_node_prompt,
    "dark_edge": _dark_edge_prompt,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def augment_enrichment(
    enrichment: Dict[str, Any],
    div_type: str,
    target_id: str,
) -> Optional[Dict[str, Any]]:
    """Call LLM to generate AI analysis augmenting rule-based enrichment.

    Returns a dict with ``summary``, ``model``, and ``generated_at`` keys,
    or ``None`` if the LLM is unavailable or the call fails.
    """
    try:
        adapter = get_adapter("on-prem")
        builder = _PROMPT_BUILDERS.get(div_type, _generic_prompt)
        prompt = builder(enrichment, target_id)
        response = await adapter.generate(prompt, max_tokens=1024, temperature=0.3)

        if not response.text.strip():
            logger.warning("LLM returned empty response for %s", target_id)
            return None

        return {
            "summary": response.text.strip(),
            "model": response.model_version,
            "generated_at": response.timestamp.isoformat(),
        }
    except Exception as e:
        logger.warning("LLM enrichment failed for %s: %s", target_id, e)
        return None
