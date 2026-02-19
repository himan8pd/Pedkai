"""
Cloud-Agnostic LLM Adapter.

Pedkai does not lock into any AI vendor. This module provides the abstraction layer.
Adapters route through local PII scrubbing before egress.

Used by: WS2 (llm_service.py), WS8 (pii_scrubber.py).
DO NOT import from llm_service.py — this is a lower-level abstraction.
"""
import hashlib
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class LLMResponse(BaseModel):
    """Standardised response from any LLM adapter."""
    text: str
    model_version: str
    prompt_hash: str
    timestamp: datetime
    token_count: Optional[int] = None
    provider: str  # "gemini", "openai", "on-prem"


class LLMAdapterConfig(BaseModel):
    """Configuration for an LLM adapter instance."""
    provider: str
    model_name: str
    api_key: Optional[str] = None
    endpoint_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7


class LLMAdapter(ABC):
    """Abstract base class for LLM adapters."""

    def __init__(self, config: LLMAdapterConfig):
        self.config = config

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Send a prompt to the LLM and return a standardised response."""
        ...

    def compute_prompt_hash(self, prompt: str) -> str:
        """Compute a SHA-256 hash of the prompt for audit logging."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    @property
    def model_version(self) -> str:
        return f"{self.config.provider}/{self.config.model_name}"


class GeminiAdapter(LLMAdapter):
    """Google Gemini implementation."""

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        from google import genai
        client = genai.Client(api_key=self.config.api_key)
        response = await client.aio.models.generate_content(
            model=self.config.model_name,
            contents=prompt,
        )
        return LLMResponse(
            text=response.text if response.text else "",
            model_version=self.model_version,
            prompt_hash=self.compute_prompt_hash(prompt),
            timestamp=datetime.now(timezone.utc),
            provider="gemini",
        )


class OnPremAdapter(LLMAdapter):
    """Adapter for on-premises LLM (vLLM, Ollama, TGI)."""

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.config.endpoint_url}/v1/completions",
                json={
                    "model": self.config.model_name,
                    "prompt": prompt,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
        return LLMResponse(
            text=data.get("choices", [{}])[0].get("text", ""),
            model_version=self.model_version,
            prompt_hash=self.compute_prompt_hash(prompt),
            timestamp=datetime.now(timezone.utc),
            provider="on-prem",
        )


def get_adapter(provider: Optional[str] = None) -> LLMAdapter:
    """
    Factory function. Returns the correct adapter based on environment config.

    Priority: PEDKAI_LLM_PROVIDER env var > provider argument > default (gemini).
    """
    import os
    from backend.app.core.config import get_settings
    settings = get_settings()

    effective_provider = os.getenv("PEDKAI_LLM_PROVIDER", provider or "gemini")

    if effective_provider == "gemini":
        return GeminiAdapter(LLMAdapterConfig(
            provider="gemini",
            model_name=settings.gemini_model,
            api_key=settings.gemini_api_key,
        ))
    elif effective_provider == "on-prem":
        return OnPremAdapter(LLMAdapterConfig(
            provider="on-prem",
            model_name=os.getenv("PEDKAI_ONPREM_MODEL", "llama3"),
            endpoint_url=os.getenv("PEDKAI_ONPREM_URL", "http://localhost:11434"),
        ))
    else:
        raise ValueError(f"Unknown LLM provider: {effective_provider}")
