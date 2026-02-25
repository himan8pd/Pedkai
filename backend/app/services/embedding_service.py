"""
Embedding Service - Generate embeddings for decision traces.

Uses Gemini embedding model to create vector representations
for semantic similarity search.
"""

from typing import Optional, List
from google import genai

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.services.embedding_local import get_local_embedding_service

settings = get_settings()
logger = get_logger(__name__)


class EmbeddingService:
    """Service for generating embeddings using the modern google-genai SDK."""
    
    def __init__(self):
        if settings.gemini_api_key:
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.provider = "gemini"
            self.model_name = "text-embedding-004"
            self.local_svc = None
            logger.info(f"Embedding service initialized with provider {self.provider} and model {self.model_name}")
        else:
            self.client = None
            self.local_svc = get_local_embedding_service()
            self.provider = self.local_svc.provider
            self.model_name = self.local_svc.model_name
            logger.warning(f"Gemini API key not configured. Falling back to local provider {self.provider} ({self.model_name}).")
    
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate an embedding vector for the given text.
        
        Returns None if the API key is not configured.
        """
        if not self.client:
            if self.local_svc:
                return await self.local_svc.generate_embedding(text)
            return None
        
        try:
            # Use the new SDK's async client
            result = await self.client.aio.models.embed_content(
                model=self.model_name,
                contents=text,
                config={
                    "task_type": "RETRIEVAL_DOCUMENT"
                }
            )
            # The new SDK returns a list of embeddings; we take the first one
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"Error generating embedding: {e}", exc_info=True)
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
