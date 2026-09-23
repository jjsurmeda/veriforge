"""Environment-driven app settings (TRD §6, §11)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://veriforge:veriforge@localhost:5432/veriforge"
    openrouter_api_key: str = ""
    litellm_master_key: str = ""

    # Auth (TRD §11): access JWT 15 min in memory; rotating 30-day refresh
    # token in an httpOnly, Secure, SameSite=Strict cookie.
    jwt_secret: str = "dev-only-insecure-secret-change-me"  # noqa: S105
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 60 * 60
    cookie_secure: bool = True
    web_origin: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: str = ""

    # Observability (TRD §15). Empty keys disable the Langfuse callback.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # RunBus tuning (TRD §7, ADR-001).
    delta_coalesce_ms: int = 50
    heartbeat_interval_seconds: int = 15
    heartbeat_sweep_seconds: int = 60

    # Ingestion (TRD §9.1). Object storage is a local directory at Stage 1;
    # slice 9 points the same ObjectStore interface at S3.
    object_storage_dir: str = ".data/objects"
    max_upload_bytes: int = 20 * 1024 * 1024
    embedding_model: str = "openrouter/openai/text-embedding-3-small"
    embedding_batch_size: int = 100
    # New ingestion jobs pause (self-retry) while more chat runs are active.
    ingest_pause_active_runs: int = 3
    ingest_pause_retry_seconds: int = 30
    # Procrastinate uses psycopg (not asyncpg); `queue` schema via search_path.
    procrastinate_conninfo: str = (
        "postgresql://veriforge:veriforge@localhost:5432/veriforge"
    )

    # Retrieval (TRD §9.2-9.4). Empty keys fall back to local behaviour:
    # fused-order rerank instead of Cohere, web search disabled.
    tavily_api_key: str = ""
    brave_api_key: str = ""
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-v3.5"
    retrieval_statement_timeout_ms: int = 1500
    # TODO(slice-4): replaced by the DecisionEngine `lexical_weight` score
    # from ingress (TRD §9.2). Fixed default until then.
    default_lexical_weight: float = 0.5
    query_cache_ttl_days: int = 30
    web_cache_ttl_hours: int = 24
    web_chunk_ttl_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
