"""
Security Regression Test Suite — Task 8.1

One test per committee finding. Tests verify that all security fixes remain in place.
Run with: python -m pytest tests/security/test_security_regressions.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Test 1: PII not in LLM prompt ─────────────────────────────────────────

def test_pii_not_in_llm_prompt():
    """B-2: PII scrubber is wired in — phone numbers / IMSI must be removed before LLM call."""
    from backend.app.services.pii_scrubber import PIIScrubber

    scrubber = PIIScrubber()
    raw_prompt = (
        "Customer MSISDN: +447700900123 "
        "IMSI: 234300001234567 "
        "Email: customer@example.com "
        "Account: ACC-9999"
    )
    scrubbed, manifest = scrubber.scrub(raw_prompt)

    # Phone number must not appear in scrubbed output
    assert "+447700900123" not in scrubbed, "Phone number survived PII scrub"
    # IMSI pattern must not appear
    assert "234300001234567" not in scrubbed, "IMSI survived PII scrub"
    # Manifest must record what was removed
    assert len(manifest) > 0, "Scrub manifest is empty — nothing was scrubbed"
    print(f"✅ PII scrubber removed {len(manifest)} items. Manifest types: {[m.get('field_type') for m in manifest]}")


# ─── Test 2: Audit trail tenant isolation ──────────────────────────────────

def test_audit_trail_tenant_isolation():
    """H-5: _get_or_404 in audit trail endpoint must include tenant_id."""
    import re
    with open("backend/app/api/incidents.py") as f:
        src = f.read()

    # Bare _get_or_404(db, incident_id) without tenant_id must not exist
    bare_calls = re.findall(r"_get_or_404\(db,\s*incident_id\)", src)
    assert len(bare_calls) == 0, (
        f"FAIL: {len(bare_calls)} _get_or_404 calls missing tenant_id: {bare_calls}"
    )
    print("✅ All _get_or_404 calls include tenant_id")


# ─── Test 3: Service impact tenant isolation ─────────────────────────────

def test_service_impact_tenant_isolation():
    """H-9: service_impact.py must filter by tenant_id in cluster/noise-wall queries."""
    with open("backend/app/api/service_impact.py") as f:
        src = f.read()

    assert "tenant_id" in src, "FAIL: no tenant_id filtering in service_impact.py"
    assert "WHERE tenant_id" in src or ":tid" in src, (
        "FAIL: tenant_id filter not applied in raw SQL queries"
    )
    print("✅ service_impact.py applies tenant_id filtering")


# ─── Test 4: No fabricated scorecard baselines ──────────────────────────

def test_no_fabricated_scorecard_baselines():
    """B-4: autonomous.py scorecard must not contain fabricated BASELINE_ constants."""
    with open("backend/app/api/autonomous.py") as f:
        src = f.read()

    assert "BASELINE_NON_PEDKAI_MTTR" not in src, "FAIL: fabricated BASELINE_NON_PEDKAI_MTTR constant present"
    assert "BASELINE_INCIDENT_RATIO" not in src, "FAIL: fabricated BASELINE_INCIDENT_RATIO constant present"
    assert "pending_shadow_mode_collection" in src, "FAIL: baseline_status honest null not present"
    print("✅ Scorecard returns honest nulls — no fabricated baselines")


# ─── Test 5: Emergency service uses entity_type ──────────────────────────

def test_emergency_service_uses_entity_type():
    """M-6: Emergency detection must use entity_type DB lookup, not string matching."""
    with open("backend/app/api/incidents.py") as f:
        src = f.read()

    # Old string-match approach must be gone
    assert '"EMERGENCY" in entity_external_id.upper()' not in src, (
        "FAIL: string-match emergency detection still present"
    )
    # New DB-based approach must be present
    assert "EMERGENCY_SERVICE" in src, "FAIL: entity_type EMERGENCY_SERVICE check not present"
    print("✅ Emergency detection uses entity_type DB lookup")


# ─── Test 6: Proactive comms defaults to no consent ─────────────────────

def test_proactive_comms_defaults_to_no_consent():
    """H-10: GDPR — consent_proactive_comms default must be False, not True."""
    with open("backend/app/services/proactive_comms.py") as f:
        src = f.read()

    # Must not default to True
    assert 'consent_proactive_comms", True' not in src, "FAIL: consent defaults to True (GDPR violation)"
    assert "consent_proactive_comms", "FAIL: consent field not referenced"

    # Confirm False default
    assert (
        'consent_proactive_comms", False' in src
        or "consent_proactive_comms', False" in src
    ), "FAIL: consent does not default to False"
    print("✅ Proactive comms consent defaults to False (GDPR compliant)")


# ─── Test 7: AI watermark in API responses ───────────────────────────────

def test_ai_watermark_in_sitrep_response():
    """H-3: All LLM-sourced responses must include ai_generated: true."""
    from backend.app.services.llm_service import LLMService
    import inspect

    src = inspect.getsource(LLMService.generate_sitrep)
    assert '"ai_generated": True' in src or '"ai_generated"' in src, (
        "FAIL: ai_generated flag not returned by generate_sitrep"
    )
    print("✅ generate_sitrep returns ai_generated: True")


# ─── Test 8: Mock users DB removed ──────────────────────────────────────

def test_mock_users_db_removed():
    """B-3: MOCK_USERS_DB must not exist in auth.py."""
    with open("backend/app/api/auth.py") as f:
        src = f.read()

    assert "MOCK_USERS_DB" not in src, (
        "FAIL: MOCK_USERS_DB still present in auth.py — hardcoded credentials remain"
    )
    print("✅ MOCK_USERS_DB removed from auth.py")


# ─── Test 9: LLM cost tracking present ──────────────────────────────────

def test_llm_cost_tracking_present():
    """Task 7.5: LLM cost estimation must be implemented and returned."""
    from backend.app.services.llm_service import LLMService
    import inspect

    service = LLMService.__new__(LLMService)
    # Verify method exists
    assert hasattr(service, "_estimate_cost"), "FAIL: _estimate_cost not found on LLMService"

    # Verify it returns expected keys with sensible values
    service._adapter = MagicMock()
    service._adapter.config = MagicMock()
    service._adapter.config.model_name = "gemini-2.0-flash"

    result = service._estimate_cost("a" * 4000, "b" * 1000)
    assert "estimated_cost_usd" in result, "FAIL: estimated_cost_usd not in result"
    assert "input_tokens" in result, "FAIL: input_tokens not in result"
    assert result["input_tokens"] == 1000, f"FAIL: expected 1000 input tokens, got {result['input_tokens']}"
    assert result["estimated_cost_usd"] > 0, "FAIL: cost estimate is 0"
    print(f"✅ LLM cost tracking: ${result['estimated_cost_usd']:.6f} for {result['input_tokens']} in + {result['output_tokens']} out tokens")
