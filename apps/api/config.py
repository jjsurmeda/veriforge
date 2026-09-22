from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven app settings (TRD §6)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://veriforge:veriforge@localhost:5432/veriforge"
    openrouter_api_key: str = ""
    litellm_master_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
