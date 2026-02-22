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
        extra="ignore", # Allow extra env vars without failing
    )
    
    # Ports and URLs (added for startup script synchronization)
    pedkai_backend_port: int = 8000
    pedkai_frontend_port: int = 3000
    next_public_api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    
    # App
    app_name: str = "Pedkai"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"
    # Secret key MUST be provided via environment (e.g. SECRET_KEY in .env)
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Auth Passwords
    admin_password: str = "admin" # Default for safety, override in .env
    operator_password: str = "operator"
    
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
    llm_confidence_threshold: float = 0.5  # Below this, use template fallback

    # AI Maturity Ladder (Task 7.1 — Amendment #15)
    # 1=Assisted (shadow), 2=Supervised (advisory, current target), 3=Autonomous (not in v1)
    ai_maturity_level: int = 2

    # Drift Detection Calibration (Task 7.2 — Amendment #24)
    drift_threshold_pct: float = 15.0       # Configurable via DRIFT_THRESHOLD_PCT env var
    drift_false_positive_window_days: int = 30  # Track FP rate over this window

    # Customer Prioritisation (Task 7.3 — Amendment #21)
    # Options: revenue | sla_tier | churn_risk | emergency_first
    customer_prioritisation_strategy: str = "revenue"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
