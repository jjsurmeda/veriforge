"""Environment-driven app settings (TRD §6, §11)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://veriforge:veriforge@localhost:5432/veriforge"
    openrouter_api_key: str = ""
    litellm_master_key: str = ""
    provider_encryption_key: str = ""
    reference_model_id: str = "anthropic/claude-haiku-4.5"

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
    procrastinate_conninfo: str = "postgresql://veriforge:veriforge@localhost:5432/veriforge"

    # Retrieval (TRD §9.2-9.4). Empty keys fall back to local behaviour:
    # fused-order rerank instead of Cohere, web search disabled.
    tavily_api_key: str = ""
    brave_api_key: str = ""
    cohere_api_key: str = ""
    cohere_rerank_model: str = "rerank-v3.5"
    # NVIDIA NIM reranking; second choice after Cohere. The model is also
    # the URL path segment on ai.api.nvidia.com.
    nvidia_api_key: str = ""
    nvidia_rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2"
    retrieval_statement_timeout_ms: int = 1500
    query_cache_ttl_days: int = 30
    web_cache_ttl_hours: int = 24
    web_chunk_ttl_days: int = 7

    # DecisionEngine (TRD §8). Jev via OpenRouter System One; Haiku-class
    # LiteLLM fallback; circuit breaker opens after 3 failures in 60 s.
    openrouter_systemone_url: str = "https://openrouter.ai/api/v1/systemone"
    jev_model: str = "typesafe/jev-1.13"
    jev_timeout_ms: int = 2000
    jev_max_state_tokens: int = 28_000
    # Every non-Jev LLM call runs on a free OpenRouter id (see
    # scripts/seed_models.py). Free ids are rate-limited per minute and per
    # day, so LiteLLM's own retry is capped rather than left unbounded.
    fallback_model: str = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
    # One LiteLLM retry, then providers/llm.py fails over once to
    # llm_fallback_model on 429/5xx/timeout (known-issues KI-7). Retrying the
    # same saturated free id four times only delayed the failure.
    llm_max_retries: int = 1
    # A retry cap is meaningless without a per-attempt deadline: a saturated
    # free endpoint can hold a streaming response open indefinitely.
    llm_timeout_seconds: float = 90.0
    llm_fallback_model: str = "openrouter/openrouter/free"
    # Calls in flight per model per process; free ids allow ~20 req/min.
    llm_max_concurrency: int = 4
    # Explicit output caps (KI-1): without one, LiteLLM asks for the model's
    # maximum and OpenRouter rejects the call with 402 on a low balance.
    llm_default_max_tokens: int = 512
    llm_max_tokens: dict[str, int] = {
        "generator": 2048,
        "rewriter": 2048,  # also writes the revised answer (graph/review.py)
        "claim_extractor": 2048,
        "planner": 1024,
        "async_judge": 1024,
    }
    # OpenRouter reasoning models think by default: seconds of latency, and
    # under a tight cap the reasoning spills into the answer. Only these
    # roles keep it on.
    llm_reasoning_roles: list[str] = ["planner"]
    breaker_failure_threshold: int = 3
    breaker_window_seconds: float = 60.0
    breaker_cooldown_seconds: float = 60.0
    shadow_sample_rate: float = 0.02

    # Environment fallback; active runtime settings can override these values.
    deep_max_hops: int = 4
    deep_credit_budget: int = 40_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
