"""
Causal Model Library - expert-defined causal patterns.
"""
import yaml
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

class CausalTemplate(BaseModel):
    id: str
    description: str
    cause_metric: str
    effect_metric: str
    entity_type_pair: List[str]
    confidence: float

class CausalModelLibrary:
    def __init__(self, template_path: Optional[str] = None):
        if template_path is None:
            template_path = os.path.join(
                os.path.dirname(__file__), "..", "data", "causal_templates.yaml"
            )
        self.template_path = template_path
        self.templates: List[CausalTemplate] = []
        self._load_templates()

    def _load_templates(self):
        try:
            with open(self.template_path, "r") as f:
                data = yaml.safe_load(f)
                self.templates = [CausalTemplate(**t) for t in data.get("causal_templates", [])]
                logger.info(f"Loaded {len(self.templates)} causal templates from {self.template_path}")
        except Exception as e:
            logger.error(f"Failed to load causal templates: {e}")

    def match_causal_templates(self, anomalies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Matches observed anomalies against expert causal templates.
        
        anomalies: List of dicts with {entity_id, entity_type, metric_name, value, etc.}
        """
        matches = []
        # Simple heuristic: for each template, look for a 'cause' and an 'effect' in the anomalies list
        for template in self.templates:
            causes = [a for a in anomalies if a.get("metric_name") == template.cause_metric 
                      and a.get("entity_type") == template.entity_type_pair[0]]
            effects = [a for a in anomalies if a.get("metric_name") == template.effect_metric 
                       and a.get("entity_type") == template.entity_type_pair[1]]

            if causes and effects:
                matches.append({
                    "template_id": template.id,
                    "description": template.description,
                    "confidence": template.confidence,
                    "evidence": {
                        "causes": [c.get("entity_id") for c in causes],
                        "effects": [e.get("entity_id") for e in effects]
                    }
                })
        
        return matches

def get_causal_library() -> CausalModelLibrary:
    return CausalModelLibrary()
