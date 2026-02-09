"""
LLM Service - Intelligence and Explanation Layer.

Uses Gemini to generate natural language explanations and recommendations
for network incidents based on RCA and Decision Memory.
"""

import google.generativeai as genai
from typing import List, Dict, Any, Optional
import json

from backend.app.core.config import get_settings

settings = get_settings()

class LLMService:
    """Service for complex reasoning and natural language explanation."""
    
    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self._model = genai.GenerativeModel(settings.gemini_model)
        else:
            self._model = None

    def _format_incident_context(self, context: Dict[str, Any]) -> str:
        """Helper to format RCA results for the prompt."""
        entity_info = f"Entity: {context.get('entity_name')} ({context.get('entity_type')})"
        upstream = "\n".join([f"- {u['entity_type']} {u['entity_name']}" for u in context.get("upstream_dependencies", [])])
        downstream = "\n".join([f"- {d['entity_type']} {d['entity_name']}" for d in context.get("downstream_impacts", [])])
        slas = "\n".join([f"- SLA: {s['entity_name']}" for s in context.get("critical_slas", [])])
        
        return f"{entity_info}\n\nUpstream Dependencies:\n{upstream}\n\nDownstream Impacts:\n{downstream}\n\nCritical SLAs:\n{slas}"

    def _format_similar_decisions(self, decisions: List[Any]) -> str:
        """Helper to format similar past decisions for the prompt."""
        if not decisions:
            return "No similar past decisions found in memory."
            
        formatted = []
        for i, d in enumerate(decisions):
            # d can be a DecisionTrace Pydantic model or ORM model
            summary = getattr(d, "decision_summary", "N/A")
            action = getattr(d, "action_taken", "N/A")
            rationale = getattr(d, "tradeoff_rationale", "N/A")
            outcome = getattr(d, "outcome", {})
            
            score = ""
            if isinstance(outcome, dict) and "success_score" in outcome:
                score = f" (Success Score: {outcome['success_score']})"
                
            formatted.append(f"Decision {i+1}:\n- Summary: {summary}\n- Action Taken: {action}\n- Rationale: {rationale}\n- Outcome: {outcome}{score}")
            
        return "\n\n".join(formatted)

    async def generate_explanation(
        self, 
        incident_context: Dict[str, Any], 
        similar_decisions: List[Any]
    ) -> str:
        """
        Synthesizes RCA results and Decision Memory into an actionable SITREP.
        """
        if not self._model:
            return "LLM Service not configured. Please set GEMINI_API_KEY."

        context_str = self._format_incident_context(incident_context)
        memory_str = self._format_similar_decisions(similar_decisions)
        
        prompt = f"""
You are Pedkai AI, the "Intelligence Wedge" of an AI-Native Telecom Operating System.
Your goal is to help a NOC (Network Operations Center) engineer reduce MTTR by providing a clear SITREP and recommendation.

### CURRENT INCIDENT CONTEXT
{context_str}

### DECISION MEMORY (Similar Past Incidents)
{memory_str}

### INSTRUCTIONS
Create a structured SITREP (Situation Report) that includes:
1. **EXECUTIVE SUMMARY**: A 1-sentence description of the status.
2. **ROOT CAUSE HYPOTHESIS**: Based on the upstream dependencies.
3. **IMPACT ASSESSMENT**: Who is affected and which SLAs are at risk.
4. **RECOMMENDED ACTION**: Based on the most successful past decisions in the memory.
5. **RATIONALE**: Why this action is recommended over others.

Maintain a professional, engineer-first tone. Use markdown formatting.
"""

        try:
            response = self._model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating LLM explanation: {e}")
            return f"Error generating automated SITREP: {str(e)}"

# Singleton instance
_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """Get the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
