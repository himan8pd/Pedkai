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
        extra="ignore",  # Allow extra env vars without failing
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
    admin_password: str = "admin"  # Default for safety, override in .env
    operator_password: str = "operator"

    # API
    api_prefix: str = "/api/v1"
    # Default for local Next.js frontend; override via ALLOWED_ORIGINS env for cloud
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Database
    database_url: str = "sqlite+aiosqlite:///./pedkai.db"
    metrics_database_url: str = "sqlite+aiosqlite:///./metrics.db"
    db_ssl_mode: str = "disable"  # "require" for production
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Gemini LLM
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    llm_sampling_rate: float = (
        1.0  # Cost control (Disabled for reliable demos, reset to 0.8 later)
    )

    # Kafka — default "localhost:9092" for local dev; set to "kafka:9092" in cloud .env
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "pedkai-consumers"

    # Multi-tenancy
    default_tenant_id: str = "casinolimit"

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

    # Evidence Fusion (TASK-104)
    # Selects the default fusion methodology used by FusionMethodologyFactory.create()
    # Options: "noisy_or" (default)
    fusion_methodology: str = "noisy_or"

    # Drift Detection Calibration (Task 7.2 — Amendment #24)
    drift_threshold_pct: float = 15.0  # Configurable via DRIFT_THRESHOLD_PCT env var
    drift_false_positive_window_days: int = 30  # Track FP rate over this window

    # Customer Prioritisation (Task 7.3 — Amendment #21)
    # Options: revenue | sla_tier | churn_risk | emergency_first
    customer_prioritisation_strategy: str = "revenue"

    # SSE Configuration (Task P0.5)
    sse_heartbeat_interval_seconds: int = 30
    sse_max_idle_seconds: int = 300
    sse_max_connections: int = 100

    # Sleeping Cell Detector (Task P2.4)
    sleeping_cell_enabled: bool = True
    sleeping_cell_scan_interval_seconds: int = 300  # 5 minutes
    sleeping_cell_interval_minutes: int = 15  # Alias for interval in minutes (converts to seconds)

    # Abeyance Memory Decay (TASK-102)
    abeyance_decay_interval_hours: int = 6  # How often the decay pass runs
    abeyance_decay_lambda: float = 0.05     # λ in exp(-λ × days); override via ABEYANCE_DECAY_LAMBDA

    # Abeyance Memory Snap Engine (LLD §9)
    abeyance_snap_threshold: float = 0.75        # Score ≥ this → SNAP
    abeyance_near_miss_threshold: float = 0.55   # Score ≥ this → NEAR_MISS (boost relevance)
    abeyance_affinity_threshold: float = 0.40    # Score ≥ this → create accumulation edge
    abeyance_near_miss_boost: float = 1.15       # Relevance multiplier for near-misses
    abeyance_temporal_gamma: float = 0.5         # γ in temporal weight formula

    # Abeyance Memory Accumulation Graph (LLD §10)
    abeyance_cluster_snap_threshold: float = 0.70  # Noisy-OR cluster score ≥ this → cluster snap
    abeyance_cluster_min_members: int = 3           # Minimum fragments for a valid cluster

    # Telemetry Replay Pipeline
    # Path to Parquet telemetry data directory
    telemetry_data_path: str = "/Volumes/Projects/Pedkai Data Store/six_telecom/output"
    # Acceleration factor: 1.0 = real-time, 120 = 1 day in ~12 minutes
    replay_acceleration: float = 120.0
    # Skip first N hours of data (already loaded into DB)
    replay_skip_hours: int = 24
    # Max messages per Kafka producer batch
    replay_batch_size: int = 500
    # Consumer batch size for DB writes
    consumer_batch_size: int = 1000
    # Consumer batch flush interval in seconds
    consumer_flush_interval_seconds: float = 5.0
    # Enable telemetry Kafka consumers on backend startup
    telemetry_consumers_enabled: bool = False
    # Kafka consumer group for telemetry ingestion
    telemetry_consumer_group: str = "pedkai-telemetry"
    # TimescaleDB retention: auto-drop chunks older than this (days, 0 = disabled)
    timescale_retention_days: int = 0


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
