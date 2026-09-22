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


@lru_cache
def get_settings() -> Settings:
    return Settings()
