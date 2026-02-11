"""
LLM Service - Intelligence and Explanation Layer.

Uses Gemini to generate natural language explanations and recommendations
for network incidents based on RCA and Decision Memory.
"""

from google import genai
from typing import List, Dict, Any, Optional
import json
import random

from backend.app.core import config
from backend.app.services.policy_engine import policy_engine
from backend.app.services.bss_service import BSSService
from backend.app.models.bss_orm import BillingAccountORM
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.core.resilience import llm_circuit_breaker

logger = get_logger(__name__)
settings = get_settings()

from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """Abstract interface for LLM providers."""
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        pass

class GeminiProvider(LLMProvider):
    """Google Gemini implementation using the modern google-genai SDK."""
    def __init__(self, api_key: str, model_name: str):
        self.client = genai.Client(api_key=api_key)
        self._model_name = model_name

    async def generate(self, prompt: str) -> str:
        response = await self.client.aio.models.generate_content(
            model=self._model_name,
            contents=prompt
        )
        return response.text

class LLMService:
    """Service for complex reasoning and natural language explanation."""
    
    def __init__(self):
        self._provider: Optional[LLMProvider] = None
        if settings.gemini_api_key:
            self._provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
        
        # Finding #36: Configurable cost control (sampling rate)
        self.sampling_rate = settings.llm_sampling_rate

    def _format_incident_context(self, context: Dict[str, Any]) -> str:
        """Helper to format RCA results for the prompt."""
        entity_info = f"Entity: {context.get('entity_name')} ({context.get('entity_type')})"
        upstream = "\n".join([f"- {u['entity_type']} {u['entity_name']}" for u in context.get("upstream_dependencies", [])])
        downstream = "\n".join([f"- {d['entity_type']} {d['entity_name']}" for d in context.get("downstream_impacts", [])])
        slas = "\n".join([f"- SLA: {s['entity_name']}" for s in context.get("critical_slas", [])])
        
        return f"{entity_info}\n\nUpstream Dependencies:\n{upstream}\n\nDownstream Impacts:\n{downstream}\n\nCritical SLAs:\n{slas}"

    async def _format_similar_decisions(self, decisions: List[Any], db_session: Optional[Any] = None) -> str:
        """Helper to format similar past decisions for the prompt, including reasoning chains."""
        if not decisions:
            return "No similar past decisions found in memory."
            
        from backend.app.services.decision_repository import DecisionTraceRepository
        repo = DecisionTraceRepository(db_session) if db_session else None
            
        formatted = []
        for i, d in enumerate(decisions):
            summary = getattr(d, "decision_summary", "N/A")
            action = getattr(d, "action_taken", "N/A")
            rationale = getattr(d, "tradeoff_rationale", "N/A")
            outcome = getattr(d, "outcome", {})
            d_id = getattr(d, "id", None)
            
            score = ""
            if isinstance(outcome, dict) and "success_score" in outcome:
                score = f" (Success Score: {outcome['success_score']})"
                
            entry = f"Decision {i+1}:\n- Summary: {summary}\n- Action Taken: {action}\n- Rationale: {rationale}\n- Outcome: {outcome}{score}"
            
            # Phase 15.3: Include Reasoning Chain (Descendants)
            if repo and d_id:
                descendants = await repo.get_descendants(d_id)
                if descendants:
                    entry += "\n- Outcome Chain (Follow-ups):"
                    for desc in descendants:
                        entry += f"\n    -> Follow-up: {desc.decision_summary} (Action: {desc.action_taken}, Outcome: {desc.outcome})"
            
            formatted.append(entry)
            
        return "\n\n".join(formatted)

    async def generate_explanation(
        self, 
        incident_context: Dict[str, Any], 
        similar_decisions: List[Any],
        causal_evidence: Optional[List[Dict[str, Any]]] = None,
        db_session: Optional[Any] = None
    ) -> str:
        """
        Synthesizes RCA results and Decision Memory into an actionable SITREP.
        Includes sampling-based cost control to prevent redundant LLM calls.
        """
        if not self._provider:
            return "LLM Provider not configured. Please set API keys."

        if random.random() > self.sampling_rate:
            # We don't skip yet, we might bypass below
            pass
        else:
            # If we are NOT in the sample, we can skip if not bypassed later
            pass
            
        # Refactor sampling logic to be determined AFTER BSS lookup
        should_bypass_sampling = False

        context_str = self._format_incident_context(incident_context)
        memory_str = await self._format_similar_decisions(similar_decisions, db_session=db_session)
        
        causal_str = "No causal analysis available."
        if causal_evidence:
            causal_lines = []
            for c in causal_evidence:
                cause = c.get("cause_metric", "Unknown")
                effect = c.get("effect_metric", "Unknown")
                p_val = c.get("p_value", 1.0)
                lag = c.get("best_lag", 0)
                causal_lines.append(f"- **{cause}** Granger-causes **{effect}** (p-value: {p_val}, lag: {lag} periods)")
            causal_str = "\n".join(causal_lines)
        
        # 3. Policy Check (The "Constitution")
        import time
        start_time = time.time()
        
        # Refactor sampling logic to be determined AFTER BSS lookup
        should_bypass_sampling = False
        bss_resolved = False
        predicted_revenue_loss = 0.0
        cumulative_revenue_loss = 0.0
        customer_tier = "BRONZE"
        
        if db_session:
            try:
                bss_service = BSSService(db_session)
                customer_ids = incident_context.get("impacted_customer_ids", [])
                
                # Finding M-7: Calculate Cumulative Risk
                cumulative_revenue_loss = await bss_service.calculate_cumulative_active_risk()
                
                if customer_ids:
                    predicted_revenue_loss = await bss_service.calculate_revenue_at_risk(customer_ids)
                    bss_resolved = True
                    
                    # Check for Gold tier in any account
                    found_gold = False
                    for cid in customer_ids:
                        account = await bss_service.get_account_by_customer_id(cid)
                        if account and account.service_plan and account.service_plan.tier == "GOLD":
                            found_gold = True
                            break
                    customer_tier = "GOLD" if found_gold else "BRONZE"
            except Exception as bse:
                logger.warning(f"BSS Context Retrieval Failed: {bse}")
        
        # Finding C-3: No hardcoded $500 fallback. If bss_resolved is False, 
        # we treat revenue as 0 and the SITREP should note it.

        policy_context = {
            "service_type": incident_context.get("service_type", "UNKNOWN"),
            "slice_id": incident_context.get("slice_id", "DEFAULT"),
            "customer_tier": customer_tier,
            "network_load": incident_context.get("metrics", {}).get("load", 50),
            "predicted_revenue_loss": predicted_revenue_loss,
            "cumulative_revenue_loss": cumulative_revenue_loss
        }
        
        policy_decision = policy_engine.evaluate(policy_context)
        policy_overhead = (time.time() - start_time) * 1000
        
        # Finding #36 & M-6 FIX: Policy-Weighted Cost Control (Post-BSS Determination)
        exclusion_threshold = policy_engine.get_parameter("sampling_exclusion_revenue_threshold", 5000)
        should_bypass_sampling = predicted_revenue_loss > exclusion_threshold if bss_resolved else False
        
        if not should_bypass_sampling and random.random() > self.sampling_rate:
            logger.info(f"Skipping LLM generation due to sampling ({self.sampling_rate}). Revenue ${predicted_revenue_loss} < ${exclusion_threshold}.")
            return f"SITREP skipped (sampling active). Please check raw RCA data. [Policies checked: {', '.join(policy_decision.applied_policies)}]"
        
        policy_section = ""
        if not policy_decision.allowed:
            policy_section = f"\n\n🛑 **POLICY BLOCK**: Action restricted by {policy_decision.reason}\n"
            policy_section += f"Required Actions: {', '.join(policy_decision.required_actions)}"
        elif policy_decision.applied_policies:
            policy_section = f"\n\n✅ **POLICY APPLIED**: {', '.join(policy_decision.applied_policies)}\n"
            policy_section += f"Mandates: {', '.join(policy_decision.required_actions)}"
        
        # Finding H-5: Deduplicate incident context in prompt
        # RCA section should ideally contain distinct results, if not provided we use a placeholder summary
        rca_context = incident_context.get("rca_results", "Generic anomaly detection triggered (RCA pending graph traversal)")

        # 4. Construct Prompt with Policy Awareness
        prompt = f"""
        You are Pedkai, an AI-Native Telco Operator.
        
        [NETWORK EVENT]
        {json.dumps(incident_context, indent=2)}
        
        [ROOT CAUSE ANALYSIS]
        {rca_context}

        [DECISION MEMORY]
        {memory_str}
        
        [CAUSAL EVIDENCE]
        {causal_str}
        
        [POLICY CONSTRAINTS]
        ALLOWED: {policy_decision.allowed}
        APPLIED POLICIES: {policy_decision.applied_policies}
        REQUIRED ACTIONS: {policy_decision.required_actions}
        REVENUE AT RISK: ${predicted_revenue_loss if bss_resolved else "UNKNOWN"}

        Task: Generate a SITREP for the NOC Engineer.
        1. Summarize the anomaly and root cause.
        2. Reference similar past decisions.
        3. Reference causal evidence if strong.
        4. Recommend an action that COMPLIES with the user policy.
        5. Clearly state if any action was blocked by policy.
        6. If revenue data was unavailable (UNKNOWN), explicitly state that.
        """

        try:
            # Use configured provider (respects settings and API key)
            if self._provider:
                response = await self._provider.generate(prompt)
                return response + policy_section
            else:
                return "LLM Provider Disconnected (Check API Key)" + policy_section

        except Exception as e:
            # Circuit Breaker Logic
            logger.error(f"LLM Generation Failed: {e}")
            return f"⚠️ AI SITREP Unavailable (Fallback): Anomaly detected in {incident_context}. Check logs.{policy_section}"

# Singleton instance
_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """Get the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
