import pytest
from backend.app.services.sovereignty_service import SovereigntyService

def test_sovereign_tenant_blocking():
    svc = SovereigntyService()
    
    # Test a sovereign tenant using an external provider
    allowed, text, reason = svc.enforce_data_sovereignty(
        "Sensitive data", 
        tenant_id="vodafone-uk-gov", 
        provider="gemini"
    )
    assert allowed is False
    assert "Sovereignty violation" in reason
    
    # Test a normal tenant using an external provider (should be allowed but scrubbed)
    allowed, text, reason = svc.enforce_data_sovereignty(
        "Call 07700 900000", 
        tenant_id="normal-tenant", 
        provider="gemini"
    )
    assert allowed is True
    assert "[PHONE_REDACTED]" in text
    
    # Test a sovereign tenant using an internal provider (should be allowed)
    allowed, text, reason = svc.enforce_data_sovereignty(
        "Sensitive data", 
        tenant_id="vodafone-uk-gov", 
        provider="minilm"
    )
    assert allowed is True
    assert "Allowed (internal provider)" in reason

def test_is_sovereign_tenant():
    svc = SovereigntyService()
    assert svc.is_sovereign_tenant("vodafone-uk-gov") is True
    assert svc.is_sovereign_tenant("gov-test") is True
    assert svc.is_sovereign_tenant("normal-tenant") is False

def test_apply_firewall_rules():
    svc = SovereigntyService()
    assert svc.apply_firewall_rules("https://googleapis.com/v1/models") is True
    assert svc.apply_firewall_rules("https://malicious-site.com/api") is False
