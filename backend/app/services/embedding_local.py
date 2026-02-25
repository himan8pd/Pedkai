"""
Local Embedding Service - specialized for On-Prem / Sovereignty.
Uses sentence-transformers with MiniLM-L6-v2 (384-dimensions).
"""
import asyncio
from typing import List, Optional
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Global variable to cache the model instance
_model_instance = None

class LocalEmbeddingService:
    """Service for generating embeddings locally using sentence-transformers."""
    
    def __init__(self):
        self.provider = "minilm"
        self.model_name = "all-MiniLM-L6-v2"
        self.dimension = 384
        logger.info(f"Local embedding service initialized (lazy-loading enabled)")

    async def _get_model(self):
        """Lazy-load the model to avoid startup overhead."""
        global _model_instance
        if _model_instance is None:
            logger.info(f"Loading local embedding model: {self.model_name}...")
            # Import here to avoid heavy dependency if not used
            from sentence_transformers import SentenceTransformer
            
            # Use run_in_executor to avoid blocking the event loop during load
            loop = asyncio.get_event_loop()
            _model_instance = await loop.run_in_executor(
                None, lambda: SentenceTransformer(self.model_name)
            )
            logger.info("Local embedding model loaded successfully.")
        return _model_instance

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate a 384-dimensional embedding vector locally.
        """
        try:
            model = await self._get_model()
            loop = asyncio.get_event_loop()
            
            # run_in_executor for the actual inference
            embedding = await loop.run_in_executor(
                None, lambda: model.encode(text)
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating local embedding: {e}", exc_info=True)
            return None

def get_local_embedding_service() -> LocalEmbeddingService:
    """Get the local embedding service instance."""
    return LocalEmbeddingService()
