"""
Embedding Service - Generate embeddings for decision traces.

Uses Gemini embedding model to create vector representations
for semantic similarity search.
"""

from typing import Optional

import google.generativeai as genai

from backend.app.core.config import get_settings

settings = get_settings()


class EmbeddingService:
    """Service for generating embeddings using Gemini."""
    
    def __init__(self):
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self._model = "models/gemini-embedding-001"
        else:
            self._model = None
    
    async def generate_embedding(self, text: str) -> Optional[list[float]]:
        """
        Generate an embedding vector for the given text.
        
        Returns None if the API key is not configured.
        """
        if not self._model:
            return None
        
        try:
            result = genai.embed_content(
                model=self._model,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None
    
    def create_decision_text(
        self,
        trigger_description: str,
        decision_summary: str,
        tradeoff_rationale: str,
        action_taken: str,
        context_description: str = "",
    ) -> str:
        """
        Create a text representation of a decision for embedding.
        
        Combines key fields into a single text that captures
        the semantic meaning of the decision.
        """
        parts = [
            f"Trigger: {trigger_description}",
            f"Decision: {decision_summary}",
            f"Rationale: {tradeoff_rationale}",
            f"Action: {action_taken}",
        ]
        
        if context_description:
            parts.append(f"Context: {context_description}")
        
        return "\n".join(parts)


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get the embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
