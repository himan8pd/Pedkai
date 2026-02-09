"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # App
    app_name: str = "Pedkai"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # API
    api_prefix: str = "/api/v1"
    
    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/pedkai"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    
    # Gemini LLM
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    
    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "pedkai-consumers"
    
    # Multi-tenancy
    default_tenant_id: str = "default"
    
    # Vector search
    embedding_dimension: int = 3072
    
    # Hugging Face
    hf_token: Optional[str] = None
    
    # Kaggle
    kaggle_username: Optional[str] = None
    kaggle_key: Optional[str] = None
    
    # Decision Memory Search Tuning
    memory_search_min_similarity: float = 0.0  # Expansive by default for MVP
    memory_search_limit: int = 5
    memory_search_global_default: bool = True


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
