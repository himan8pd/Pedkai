"""
Sovereignty Service - Multi-Tenant Egress Control and Guardrails.
Ensures data residency and sovereignty requirements are met before sending data to external providers.
"""
from typing import Tuple, List, Dict, Any, Optional
from backend.app.core.logging import get_logger
from backend.app.services.pii_scrubber import PIIScrubber

logger = get_logger(__name__)

class SovereigntyService:
    """
    Handles data sovereignty enforcement for multi-tenant environments.
    
    Roles:
    1. Egress Filtering: Block sensitive data from leaving the Pedkai enclave.
    2. Provider Isolation: Ensure sovereign tenants only use approved (local/on-prem) providers.
    3. Stricter Scrubbing: Apply aggressive PII reduction for non-sovereign but sensitive egress.
    """
    
    def __init__(self):
        self._scrubber = PIIScrubber()
        # Mock sovereignty requirements - in production this would be in the Tenant model
        self.SOVEREIGN_TENANTS = ["vodafone-uk-gov", "bt-military", "central-bank-hub"]

    def is_sovereign_tenant(self, tenant_id: str) -> bool:
        """Check if a tenant has strict sovereignty requirements."""
        return tenant_id in self.SOVEREIGN_TENANTS or tenant_id.startswith("gov-")

    def enforce_data_sovereignty(
        self, 
        text: str, 
        tenant_id: str, 
        provider: str
    ) -> Tuple[bool, str, str]:
        """
        Enforce sovereignty rules before data leaves the system.
        
        Returns:
        (is_allowed, processed_text, reason)
        """
        is_sovereign = self.is_sovereign_tenant(tenant_id)
        
        # Rule 1: Sovereign tenants CANNOT use external providers (e.g., Gemini)
        if is_sovereign and provider == "gemini":
            logger.warning(f"Sovereignty Block: Tenant {tenant_id} attempted to use external provider {provider}")
            return False, text, f"Sovereignty violation: Sovereign tenant {tenant_id} cannot egress to {provider}"
            
        # Rule 2: Non-sovereign tenants still get aggressive scrubbing for external providers
        if provider == "gemini":
            scrubbed_text, manifest = self._scrubber.scrub(text)
            if manifest:
                logger.info(f"Sovereignty Scrubbing: Removed {len(manifest)} items for egress to {provider}")
            return True, scrubbed_text, "Allowed with standard scrubbing"
            
        # Rule 3: On-prem providers (like MiniLM) allowed for everyone without blocking
        return True, text, "Allowed (internal provider)"

    def apply_firewall_rules(self, endpoint: str) -> bool:
        """
        Mock implementation of egress IP/DNS firewall check.
        In a real NFV environment, this would call a gateway API.
        """
        allowed_domains = ["googleapis.com", "huggingface.co", "localhost"]
        for domain in allowed_domains:
            if domain in endpoint:
                return True
        return False

def get_sovereignty_service() -> SovereigntyService:
    """Get the sovereignty service instance."""
    return SovereigntyService()
