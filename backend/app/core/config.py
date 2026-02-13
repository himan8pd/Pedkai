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
    log_level: str = "INFO"
    # Secret key MUST be provided via environment (e.g. SECRET_KEY in .env)
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # API
    api_prefix: str = "/api/v1"
    # Default for local Next.js frontend; override via ALLOWED_ORIGINS env for cloud
    allowed_origins: list[str] = ["http://localhost:3000"]
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./pedkai.db"
    metrics_database_url: str = "sqlite+aiosqlite:///./metrics.db"
    db_ssl_mode: str = "disable" # "require" for production
    database_pool_size: int = 5
    database_max_overflow: int = 10
    
    # Gemini LLM
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    llm_sampling_rate: float = 1.0 # Cost control (Disabled for reliable demos, reset to 0.8 later)
    
    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092" # hard coded for demo, remove " = "localhost:9092"" for live env.
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
    memory_search_min_similarity: float = 0.9  # Expansive by default for MVP
    memory_search_limit: int = 5
    memory_search_global_default: bool = True


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
