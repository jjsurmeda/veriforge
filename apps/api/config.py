"""Environment-driven app settings (TRD §6, §11)."""

from collections.abc import Mapping
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
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

    # Deployment environment. Read at startup: `production` is what makes the
    # dev-only behaviour (the dev-log email transport) refuse to run, so it
    # cannot be left at its default on a real deployment.
    environment: Literal["development", "staging", "production"] = "development"

    # Signup control (item 4). `invite` is the production default: a private
    # beta with a handful of invited users must not be reachable by anyone
    # who guesses a URL, and the default is the safe one because forgetting
    # to set it is the failure mode that leaks the deployment.
    signup_mode: Literal["open", "invite", "closed"] = "invite"
    # In-process rate limits (item 4, ADR-001). 10 auth attempts a minute per
    # IP is the example; the defaults are deliberately tight on the endpoints
    # worth brute-forcing and looser on run creation, where a burst is normal
    # (the Auto mode re-enters retrieval, not run creation, so one request
    # per turn is the honest count).
    rate_limit_signup: int = 10
    rate_limit_signup_window_seconds: float = 60.0
    rate_limit_login: int = 10
    rate_limit_login_window_seconds: float = 60.0
    rate_limit_run: int = 60
    rate_limit_run_window_seconds: float = 60.0

    # Email (AC-1 password reset). `dev_log` writes the message to the
    # log instead of sending it, and is refused when ENVIRONMENT=production.
    # `smtp` sends for real; AWS SES publishes an SMTP endpoint, so slice 9
    # points these at SES with no code change.
    email_transport: Literal["smtp", "dev_log"] = "dev_log"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 10.0

    # Observability (TRD §15). Empty keys disable the Langfuse callback.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # The pinned SDK (`langfuse<3`) reads `LANGFUSE_HOST`, and with no host
    # it falls back to the EU default — where a JP project's keys silently
    # fail to authenticate, so traces stop arriving with no error anywhere
    # (KI-21: 301 traces, then nothing). `LANGFUSE_BASE_URL` is accepted as an
    # alias because that is the name already in `.env`; both names work and
    # the SDK's own name wins when both are set.
    langfuse_host: str = Field(
        default="", validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL")
    )

    # RunBus tuning (TRD §7, ADR-001).
    delta_coalesce_ms: int = 50
    heartbeat_interval_seconds: int = 15
    heartbeat_sweep_seconds: int = 60

    # Ingestion (TRD §9.1). Object storage is a local directory at Stage 1;
    # slice 9 points the same ObjectStore interface at S3.
    object_storage_dir: str = ".data/objects"
    max_upload_bytes: int = 20 * 1024 * 1024
    embedding_model: str = "openrouter/openai/text-embedding-3-large"
    # text-embedding-3-large defaults to 3072 dims; pin 1536 so the vector
    # fits `chunks.embedding vector(1536)` unchanged (TRD §9.2, round 2).
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 100
    # New ingestion jobs pause (self-retry) while more chat runs are active.
    ingest_pause_active_runs: int = 3
    # OCR (beta, TRD §9.1). Compute only: no credits. The engine id itself is
    # the runtime setting `ocr.engine`; these are the env-level limits.
    ocr_enabled: bool = True
    ocr_languages: str = "eng+spa+fra+chi_sim+jpn+fil"
    ocr_dpi: int = 200
    ocr_max_pages_per_document: int = 50
    ocr_page_timeout_seconds: float = 30.0
    ocr_min_confidence: int = 30
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
    # Every non-Jev LLM call runs on one OpenRouter id (see
    # scripts/seed_models.py), and it is a paid one: the eval baselines were
    # measured on it, and the gate refuses to compare across models, so a run
    # that lands on a `:free` id is not a regression check. LiteLLM's retry is
    # capped rather than unbounded because the endpoint is still per-minute
    # limited.
    fallback_model: str = "openrouter/openai/gpt-4o-mini"
    # One LiteLLM retry, then providers/llm.py fails over once to
    # llm_fallback_model on 429/5xx/timeout (known-issues KI-7). Retrying the
    # same saturated id four times only delayed the failure.
    llm_max_retries: int = 1
    # A retry cap is meaningless without a per-attempt deadline: a saturated
    # endpoint can hold a streaming response open indefinitely.
    llm_timeout_seconds: float = 90.0
    llm_fallback_model: str = "openrouter/openai/gpt-4o-mini"
    # Calls in flight per model per process; OpenRouter allows ~20 req/min on
    # a free id and more on a paid one.
    llm_max_concurrency: int = 4
    # Explicit output caps: without one, LiteLLM asks for the model's
    # maximum and OpenRouter rejects the call with 402 on a low balance.
    llm_default_max_tokens: int = 512
    llm_max_tokens: dict[str, int] = {
        "generator": 2048,
        "rewriter": 2048,  # also writes the revised answer (graph/review.py)
        "claim_extractor": 2048,
        "planner": 1024,
        "async_judge": 1024,
        "summariser": 2048,
        # The fallback engine answers the WHOLE batched decide call in one
        # JSON object. The largest batch is the post-sanitize sufficiency
        # call with its per-passage entity questions (8-12 Noul answers,
        # each with reasoning), whose response exceeds the 512 default:
        # when jev was degraded, every such batch truncated mid-JSON at
        # the same offset and failed the item. 4096 leaves wide
        # headroom over the largest observed response.
        "decision_fallback": 4096,
    }
    # OpenRouter reasoning models think by default: seconds of latency, and
    # under a tight cap the reasoning spills into the answer. Only these
    # roles keep it on.
    llm_reasoning_roles: list[str] = ["planner"]
    breaker_failure_threshold: int = 3
    breaker_window_seconds: float = 60.0
    breaker_cooldown_seconds: float = 60.0
    shadow_sample_rate: float = 0.02

    # The generator's temperature is NOT here. It is the runtime setting
    # `generation.temperature` (runtime.py DEFAULT_DATA), so an admin can
    # change it from the admin API without a redeploy — it is a product-quality
    # decision made on the full eval sets, like every other tunable
    # (reranker, thresholds, top_k). `None` there means "send no temperature",
    # so the provider default applies and generation is unchanged.

    # Environment fallback; active runtime settings can override these values.
    deep_max_hops: int = 4
    deep_credit_budget: int = 40_000


@lru_cache
def get_settings() -> Settings:
    return Settings()


# The model every non-Jev role runs on: the one the eval baselines were
# measured with, spelled the way LiteLLM spells it everywhere else in this
# package (`openrouter/` prefix). Seeded by `scripts/seed_models.py`.
DEFAULT_MODEL_ID = "openai/gpt-4o-mini"

# The generator role runs on its own model (ADR-007): DeepSeek V4 Pro, pinned by
# slug, priced per 1M tokens at OpenRouter's list price (KI-90: 53 billed calls
# came to 0.98x of this; single runs swing 0.77x to 1.12x with provider routing).
GENERATOR_MODEL_ID = "deepseek/deepseek-v4-pro"
GENERATOR_PRICE_IN = 0.955
GENERATOR_PRICE_OUT = 1.911
GENERATOR_CONTEXT_WINDOW = 1_048_576

# The async quality judge (graph/async_scoring.py) is the `async_judge` role. This is its default
# binding: seeded once, then an admin changes it on the Roles page. Without a binding the call
# still runs on this model.
ASYNC_JUDGE_MODEL_ID = "anthropic/claude-haiku-4.5"


def is_free_model(model_id: str) -> bool:
    """Whether a model id is an OpenRouter free-tier id.

    Two spellings reach us: the explicit `:free` suffix
    (`nvidia/nemotron-3-super-120b-a12b:free`) and OpenRouter's free router,
    which is the bare word `free` as its last path segment
    (`openrouter/openrouter/free`). Both are free ids, and neither is a
    product default.
    """
    return model_id.endswith(":free") or model_id.rpartition("/")[2] == "free"


def free_model_violations(
    settings: Settings, role_models: Mapping[str, str]
) -> list[str]:
    """Every way this configuration can reach a free model, named.

    `role_models` is the role → model_id binding table as stored in
    `model_roles`, so a binding seeded by `scripts/seed_models.py --free` is
    reported against the role it affects rather than as a count. Pure — it
    reads no database and calls no provider — because boot calls it before it
    opens a connection, and because a check that can fail silently is how a
    free tier reaches production.
    """
    violations = [
        f"role {role!r} is bound to the free model {model_id!r}"
        for role, model_id in sorted(role_models.items())
        if is_free_model(model_id)
    ]
    violations.extend(
        f"{name} is the free model {getattr(settings, name)!r}"
        for name in ("fallback_model", "llm_fallback_model")
        if is_free_model(getattr(settings, name))
    )
    return violations
