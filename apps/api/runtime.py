from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Setting

DEFAULT_DATA: dict[str, Any] = {
    "decision_engine_mode": "auto",
    "shadow_sample_rate": 0.02,
    "trace_sample_rate": 1.0,
    "quota_estimates": {"fast": 3000, "auto": 8000, "deep": 30000},
    "retrieval": {
        "top_k": 8,
        "fused_limit": 40,
        "vec_limit": 50,
        "lex_limit": 50,
        "rrf_k": 60,
        "rerank": True,
        "hop_limit": 4,
        "retry_limit": 2,
    },
    "deep": {"per_run_credit_cap": 40000},
    "guardrails": {
        "enabled": True,
        "actions": {
            "injection": "block",
            "jailbreak": "block",
            "pii": "warn",
            "off_topic": "warn",
            "toxicity": "block",
            "secrets": "redact",
        },
    },
    "web_search_provider": "tavily",
    "web_search_keys": {},
    "source_priority": "documents_first",
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge(current, value)
        else:
            result[key] = value
    return result


@dataclass(frozen=True)
class RuntimeSettings:
    version: int
    data: dict[str, Any]

    @classmethod
    def from_data(cls, version: int, data: dict[str, Any] | None) -> RuntimeSettings:
        return cls(version=version, data=_merge(DEFAULT_DATA, data or {}))

    def get(self, path: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


async def load_active_runtime(session: AsyncSession) -> RuntimeSettings:
    row = (
        await session.execute(select(Setting).where(Setting.active).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return RuntimeSettings.from_data(0, {})
    return RuntimeSettings.from_data(row.version, row.data)


async def load_runtime_version(session: AsyncSession, version: int | None) -> RuntimeSettings:
    if version is None:
        return await load_active_runtime(session)
    row = (
        await session.execute(select(Setting).where(Setting.version == version).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return RuntimeSettings.from_data(version, {})
    return RuntimeSettings.from_data(row.version, row.data)


_settings: ContextVar[RuntimeSettings | None] = ContextVar(
    "veriforge_runtime_settings", default=None
)


def get_runtime_settings() -> RuntimeSettings | None:
    return _settings.get()


def set_runtime_settings(settings: RuntimeSettings) -> Token[RuntimeSettings | None]:
    return _settings.set(settings)


def reset_runtime_settings(token: Token[RuntimeSettings | None]) -> None:
    _settings.reset(token)


def runtime_value(path: str, default: Any) -> Any:
    settings = get_runtime_settings()
    return settings.get(path, default) if settings is not None else default
