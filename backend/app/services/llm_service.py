"""
LLM Service - Intelligence and Explanation Layer.

Uses a cloud-agnostic LLMAdapter (llm_adapter.py) to generate natural language explanations
and recommendations for network incidents based on RCA and Decision Memory.
"""

from typing import List, Dict, Any, Optional, Tuple
import json
import random
import hashlib
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core import config
from backend.app.services.policy_engine import get_policy_engine
from backend.app.services.bss_service import BSSService
from backend.app.models.bss_orm import BillingAccountORM
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.core.resilience import llm_circuit_breaker
from backend.app.services.pii_scrubber import PIIScrubber
from backend.app.services.llm_adapter import get_adapter
from backend.app.services.causal_models import get_causal_library
from backend.app.services.sovereignty_service import get_sovereignty_service

logger = get_logger(__name__)
settings = get_settings()


class LLMService:
    """Service for complex reasoning and natural language explanation."""
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._adapter = get_adapter()  # Uses PEDKAI_LLM_PROVIDER env var
        self._pii_scrubber = PIIScrubber()
        self.session_factory = session_factory
        
        # Finding #36: Configurable cost control (sampling rate)
        self.sampling_rate = settings.llm_sampling_rate

    @asynccontextmanager
    async def _get_session(self, session: Optional[AsyncSession] = None):
        if session:
            yield session
        else:
            async with self.session_factory() as new_session:
                try:
                    yield new_session
                    await new_session.commit()
                except Exception:
                    await new_session.rollback()
                    raise
                finally:
                    await new_session.close()

    async def _compute_confidence(
        self,
        llm_text: str,
        decision_memory_hits: int,
        causal_evidence_count: int,
        session: Optional[AsyncSession] = None,
    ) -> float:
        """
        Compute a calibrated confidence score [0.0, 1.0].
        P3.5:
        1. Base Confidence = matches against decision memory (min 0.3, max 0.8)
        2. Expert Multiplier = +0.1 per expert causal match (max +0.2)
        3. Calibrated Lookup: If >=50 operator feedback scores exist in similar bins, 
           use the historical average score scaled to 0-1.
        """
        # 1. Heuristic Base
        base_confidence = min(0.3 + (decision_memory_hits * 0.1), 0.8)
        
        # 2. Expert Multiplier
        expert_bonus = min(causal_evidence_count * 0.1, 0.2)
        heuristic_score = base_confidence + expert_bonus
        
        # 3. Calibrated Lookup
        try:
            from backend.app.services.decision_repository import DecisionTraceRepository
            repo = DecisionTraceRepository(self.session_factory)
            
            # Bin by caps to ensure stability
            bin_memory = min(decision_memory_hits, 4)
            bin_causal = min(causal_evidence_count, 2)
            
            stats = await repo.get_calibration_stats(bin_memory, bin_causal, session=session)
            
            if stats["total_votes"] >= 50:
                # Scale 1-5 stars to 0.0-1.0
                # (avg - 1) / 4.0
                calibrated_score = (stats["avg_score"] - 1.0) / 4.0
                logger.info(f"Using calibrated confidence: {calibrated_score:.2f} (based on {stats['total_votes']} votes in bin {bin_memory}/{bin_causal})")
                return round(calibrated_score, 2)
        except Exception as e:
            logger.warning(f"Confidence calibration lookup failed: {e}")
            
        return round(min(heuristic_score, 0.95), 2)

    def _estimate_cost(self, prompt: str, response_text: str) -> dict:
        """Estimate Gemini API cost per LLM call. Task 7.5 (Amendment #20).

        Gemini Flash pricing (approximate, verify at cloud.google.com/vertex-ai/pricing):
          $0.075 / 1M input tokens | $0.30 / 1M output tokens
        Rough token estimate: 4 chars per token.
        """
        input_tokens = len(prompt) // 4
        output_tokens = len(response_text) // 4
        input_cost = (input_tokens / 1_000_000) * 0.075
        output_cost = (output_tokens / 1_000_000) * 0.30
        model_name = (
            self._adapter.config.model_name
            if hasattr(self._adapter, 'config') and self._adapter.config
            else "unknown"
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(input_cost + output_cost, 6),
            "model": model_name,
        }

    def _format_incident_context(self, context: Dict[str, Any]) -> str:
        """Helper to format RCA results for the prompt."""
        entity_info = f"Entity: {context.get('entity_name')} ({context.get('entity_type')})"
        upstream = "\n".join([f"- {u['entity_type']} {u['entity_name']}" for u in context.get("upstream_dependencies", [])])
        downstream = "\n".join([f"- {d['entity_type']} {d['entity_name']}" for d in context.get("downstream_impacts", [])])
        slas = "\n".join([f"- SLA: {s['entity_name']}" for s in context.get("critical_slas", [])])
        
        return f"{entity_info}\n\nUpstream Dependencies:\n{upstream}\n\nDownstream Impacts:\n{downstream}\n\nCritical SLAs:\n{slas}"

    async def _format_similar_decisions(self, decisions: List[Any], session: Optional[AsyncSession] = None) -> str:
        """Helper to format similar past decisions for the prompt, including reasoning chains."""
        if not decisions:
            return "No similar past decisions found in memory."
            
        from backend.app.services.decision_repository import DecisionTraceRepository
        repo = DecisionTraceRepository(self.session_factory)
            
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
                    for desc in descendants:
                        entry += f"\n    -> Follow-up: {desc.decision_summary} (Action: {desc.action_taken}, Outcome: {desc.outcome})"
            
            formatted.append(entry)
            
        return "\n\n".join(formatted)

    async def generate_explanation(
        self, 
        incident_context: Dict[str, Any], 
        similar_decisions: List[Any],
        causal_evidence: Optional[List[Dict[str, Any]]] = None,
        db_session: Optional[Any] = None,
        decision_memory_hits: int = 0,
        causal_evidence_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Synthesizes RCA results and Decision Memory into an actionable SITREP.
        Returns a dict with text, confidence, model_version, prompt_hash, ai_generated.
        Includes sampling-based cost control to prevent redundant LLM calls.
        """
        return await self.generate_sitrep(
            incident_context,
            similar_decisions,
            causal_evidence,
            db_session,
            decision_memory_hits,
            causal_evidence_count
        )

    async def generate_sitrep(
        self, 
        incident_context: Dict[str, Any], 
        similar_decisions: List[Any],
        causal_evidence: Optional[List[Dict[str, Any]]] = None,
        session: Optional[AsyncSession] = None,
        decision_memory_hits: int = 0,
        causal_evidence_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Synthesizes RCA results and Decision Memory into an actionable SITREP.
        Returns a dict with text, confidence, model_version, prompt_hash, ai_generated.
        Includes sampling-based cost control to prevent redundant LLM calls.
        """
        if not self._adapter:
            return {
                "text": "LLM Adapter not configured. Please set API keys.",
                "confidence": 0.0,
                "model_version": "none",
                "prompt_hash": "",
                "ai_generated": True,
                "scrub_manifest": [],
            }

        # P3.1: Expert Causal Matching
        causal_lib = get_causal_library()
        expert_matches = causal_lib.match_causal_templates(incident_context.get("anomalies", []))
        
        context_str = self._format_incident_context(incident_context)
        memory_str = await self._format_similar_decisions(similar_decisions, session=session)
        
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
            
        if expert_matches:
            expert_lines = ["\n[EXPERT CAUSAL EVIDENCE]"]
            for m in expert_matches:
                expert_lines.append(f"- {m['description']} (Expert Confidence: {m['confidence']})")
            causal_str += "\n" + "\n".join(expert_lines)
        
        # 3. Policy Check (The "Constitution")
        import time
        start_time = time.time()
        
        bss_resolved = False
        predicted_revenue_loss = 0.0
        cumulative_revenue_loss = 0.0
        customer_tier = "BRONZE"
        
        try:
            bss_service = BSSService(self.session_factory)
            customer_ids = incident_context.get("impacted_customer_ids", [])
            
            # Finding M-7: Calculate Cumulative Risk
            cumulative_revenue_loss = await bss_service.calculate_cumulative_active_risk(session=session)
            
            if customer_ids:
                predicted_revenue_loss = await bss_service.calculate_revenue_at_risk(customer_ids, session=session)
                bss_resolved = True
                
                # Check for Gold tier in any account
                found_gold = False
                for cid in customer_ids:
                    account = await bss_service.get_account_by_customer_id(cid, session=session)
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
        
        engine = get_policy_engine()
        policy_decision = engine.evaluate(policy_context)
        policy_overhead = (time.time() - start_time) * 1000
        
        # Finding #36 & M-6 FIX: Policy-Weighted Cost Control (Post-BSS Determination)
        exclusion_threshold = engine.get_parameter("sampling_exclusion_revenue_threshold", 5000)
        should_bypass_sampling = predicted_revenue_loss > exclusion_threshold if bss_resolved else False
        
        if not should_bypass_sampling and random.random() > self.sampling_rate:
            logger.info(f"Skipping LLM generation due to sampling ({self.sampling_rate}). Revenue ${predicted_revenue_loss} < ${exclusion_threshold}.")
            text = f"SITREP skipped (sampling active). Please check raw RCA data. [Policies checked: {', '.join(policy_decision.applied_policies)}]"
            return {"text": text, "confidence": 0.0, "model_version": "skipped", "prompt_hash": "", "ai_generated": True, "scrub_manifest": []}
        
        policy_section = ""
        if not policy_decision.allowed:
            policy_section = f"\n\n🛑 **POLICY BLOCK**: Action restricted by {policy_decision.reason}\n"
            policy_section += f"Required Actions: {', '.join(policy_decision.required_actions)}"
        elif policy_decision.applied_policies:
            policy_section = f"\n\n✅ **POLICY APPLIED**: {', '.join(policy_decision.applied_policies)}\n"
            policy_section += f"Mandates: {', '.join(policy_decision.required_actions)}"
        
        # Finding H-5: Deduplicate incident context in prompt
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

        # B-2 FIX: Scrub PII before sending to external LLM
        prompt, scrub_manifest = self._pii_scrubber.scrub(prompt)
        if scrub_manifest:
            logger.info(
                f"PII scrubber removed {len(scrub_manifest)} items before LLM call. "
                f"Prompt hash: {hashlib.sha256(prompt.encode()).hexdigest()[:16]}"
            )

        # 4. Sovereignty Enforcement (Egress Control)
        from backend.app.services.sovereignty_service import get_sovereignty_service
        sov_service = get_sovereignty_service()
        allowed, scrubbed_prompt, reason = sov_service.enforce_data_sovereignty(
            prompt, 
            tenant_id=incident_context.get("tenant_id", "default"),
            provider=self._adapter.__class__.__name__.lower()  # Should match adapter type
        )
        
        if not allowed:
            logger.warning(f"SITREP Blocked by Sovereignty: {reason}")
            return {
                "text": f"⚠️ [SOVEREIGNTY BLOCK] {reason}. Manual RCA required.",
                "confidence": 0.0,
                "model_version": "sovereignty-guard",
                "ai_generated": True,
                "scrub_manifest": []
            }
        
        prompt = scrubbed_prompt
        
        try:
            llm_resp = await self._adapter.generate(prompt)
            # LLMResponse is a Pydantic model — access as attributes
            llm_text = (llm_resp.text if hasattr(llm_resp, "text") else str(llm_resp)) + policy_section
            model_version = llm_resp.model_version if hasattr(llm_resp, "model_version") else "unknown"
            prompt_hash = llm_resp.prompt_hash if hasattr(llm_resp, "prompt_hash") else ""

            # Task 3.2: Confidence scoring
            confidence = await self._compute_confidence(llm_text, decision_memory_hits, causal_evidence_count, session=session)
            entity_id = incident_context.get("entity_id", "unknown")
            if confidence < settings.llm_confidence_threshold:
                llm_text = (
                    f"[LOW CONFIDENCE — TEMPLATE FALLBACK]\n"
                    f"Anomaly detected on entity {entity_id}. "
                    f"Insufficient historical data for AI analysis. "
                    f"Manual investigation recommended."
                ) + policy_section

            # Task 7.5: Estimate and log per-call LLM cost (Amendment #20)
            cost_estimate = self._estimate_cost(prompt, llm_text)
            logger.info(
                f"LLM cost estimate: ${cost_estimate['estimated_cost_usd']:.6f} USD "
                f"({cost_estimate['input_tokens']} in + {cost_estimate['output_tokens']} out tokens) "
                f"model={cost_estimate['model']}"
            )

            return {
                "text": llm_text,
                "confidence": confidence,
                "model_version": model_version,
                "prompt_hash": prompt_hash,
                "ai_generated": True,
                "scrub_manifest": scrub_manifest,
                "llm_cost_usd": cost_estimate["estimated_cost_usd"],
                "llm_input_tokens": cost_estimate["input_tokens"],
                "llm_output_tokens": cost_estimate["output_tokens"],
            }

        except Exception as e:
            logger.error(f"LLM Generation Failed: {e}")
            return {
                "text": f"⚠️ AI SITREP Unavailable (Fallback): Check logs.{policy_section}",
                "confidence": 0.0,
                "model_version": "error",
                "prompt_hash": "",
                "ai_generated": True,
                "scrub_manifest": scrub_manifest if 'scrub_manifest' in dir() else [],
            }

def get_llm_service() -> LLMService:
    """Get the LLM service instance."""
    from backend.app.core.database import async_session_maker
    return LLMService(async_session_maker)
