from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    AuditLog,
    LlmProvider,
    Model,
    ModelRole,
    Plan,
    Setting,
    User,
    UserQuotaOverride,
)
from errors import AppError
from providers.credentials import decrypt_provider_key, encrypt_provider_key
from runtime import RuntimeSettings
from schemas.admin import (
    AdminModelOut,
    AuditOut,
    ModelCreate,
    ModelPatch,
    PlanCreate,
    PlanOut,
    PlanPatch,
    ProviderCreate,
    ProviderOut,
    ProviderPatch,
    RoleOut,
    RoleUpsert,
    SettingsOut,
    UserOut,
    UserPatch,
)

_ALLOWED_SETTINGS = {
    "decision_engine_mode",
    "shadow_sample_rate",
    "trace_sample_rate",
    "quota_estimates",
    "retrieval",
    "deep",
    "guardrails",
    "web_search_provider",
    "web_search_keys",
    "source_priority",
    "thresholds",
}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        current = result.get(key)
        result[key] = (
            _deep_merge(current, value)
            if isinstance(current, dict) and isinstance(value, dict)
            else value
        )
    return result


def _validate_settings(data: dict[str, Any]) -> None:
    mode = data.get("decision_engine_mode")
    if mode not in {"auto", "jev_only", "fallback_only"}:
        raise AppError("invalid_settings", "Invalid decision engine mode", status_code=422)
    for key in ("shadow_sample_rate", "trace_sample_rate"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise AppError("invalid_settings", f"{key} must be between 0 and 1", status_code=422)
    estimates = data.get("quota_estimates", {})
    if not isinstance(estimates, dict) or any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        for value in estimates.values()
    ):
        raise AppError("invalid_settings", "Quota estimates must be non-negative", status_code=422)
    retrieval = data.get("retrieval", {})
    if not isinstance(retrieval, dict):
        raise AppError("invalid_settings", "Retrieval settings must be an object", status_code=422)
    for key in ("top_k", "fused_limit", "vec_limit", "lex_limit", "rrf_k", "hop_limit"):
        value = retrieval.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            raise AppError(
                "invalid_settings", f"retrieval.{key} must be a positive integer", status_code=422
            )
    retry_limit = retrieval.get("retry_limit")
    if retry_limit is not None and (
        not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or retry_limit < 0
    ):
        raise AppError(
            "invalid_settings", "retrieval.retry_limit must be non-negative", status_code=422
        )
    thresholds = data.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise AppError("invalid_settings", "Thresholds must be an object", status_code=422)
    for values in thresholds.values():
        if not isinstance(values, dict) or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1
            for value in values.values()
        ):
            raise AppError(
                "invalid_settings", "Thresholds must be between 0 and 1", status_code=422
            )
    deep = data.get("deep", {})
    if not isinstance(deep, dict) or (
        deep.get("per_run_credit_cap") is not None
        and (
            not isinstance(deep["per_run_credit_cap"], int)
            or isinstance(deep["per_run_credit_cap"], bool)
            or deep["per_run_credit_cap"] < 1
        )
    ):
        raise AppError("invalid_settings", "Deep credit cap must be positive", status_code=422)
    guardrails = data.get("guardrails", {})
    if not isinstance(guardrails, dict) or not isinstance(guardrails.get("enabled", True), bool):
        raise AppError("invalid_settings", "Guardrails must be an object", status_code=422)
    actions = guardrails.get("actions", {})
    if not isinstance(actions, dict) or any(
        value not in {"block", "warn", "redact", "off", "disabled"} for value in actions.values()
    ):
        raise AppError("invalid_settings", "Invalid guardrail action", status_code=422)
    keys = data.get("web_search_keys", {})
    if not isinstance(keys, dict) or any(not isinstance(value, str) for value in keys.values()):
        raise AppError("invalid_settings", "Web search keys must be strings", status_code=422)
    if data.get("web_search_provider") not in {"tavily", "brave"}:
        raise AppError("invalid_settings", "Invalid web search provider", status_code=422)
    if data.get("source_priority") not in {"documents_first", "web_first"}:
        raise AppError("invalid_settings", "Invalid source priority", status_code=422)


def _not_found(entity: str) -> AppError:
    return AppError(f"{entity}_not_found", f"{entity} not found", status_code=404)


def _provider_out(row: LlmProvider) -> ProviderOut:
    return ProviderOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        enabled=row.enabled,
        has_api_key=row.api_key_enc is not None,
    )


def _model_out(row: Model) -> AdminModelOut:
    return AdminModelOut(
        id=row.id,
        provider_id=row.provider_id,
        model_id=row.model_id,
        price_in=float(row.price_in) if row.price_in is not None else None,
        price_out=float(row.price_out) if row.price_out is not None else None,
        context_window=row.context_window,
        capabilities=row.capabilities,
        enabled=row.enabled,
    )


def settings_out(row: Setting) -> SettingsOut:
    return SettingsOut(
        version=row.version, data=row.data, active=row.active, created_at=row.created_at
    )


def _audit(
    session: AsyncSession,
    *,
    actor_id: UUID,
    action: str,
    target: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        AuditLog(actor_id=actor_id, action=action, target=target, before=before, after=after)
    )


async def _lock_settings(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(1907, 1)"))


async def get_settings_row(session: AsyncSession, *, lock: bool = True) -> Setting:
    if lock:
        await _lock_settings(session)
    statement = select(Setting).where(Setting.active).limit(1)
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is not None:
        return row

    latest = (
        await session.execute(
            select(Setting).order_by(Setting.version.desc()).limit(1).with_for_update()
        )
    ).scalar_one_or_none()
    if latest is not None:
        latest.active = True
        return latest

    row = Setting(version=1, data={}, active=True)
    session.add(row)
    await session.flush()
    return row


async def list_settings(session: AsyncSession) -> list[SettingsOut]:
    rows = (await session.execute(select(Setting).order_by(Setting.version.desc()))).scalars().all()
    return [settings_out(row) for row in rows]


async def update_settings(
    session: AsyncSession, *, actor_id: UUID, patch: dict[str, Any]
) -> SettingsOut:
    unknown = set(patch) - _ALLOWED_SETTINGS
    if unknown:
        raise AppError("invalid_settings", f"Unknown settings: {sorted(unknown)}", status_code=422)
    current = await get_settings_row(session, lock=True)
    before = dict(current.data)
    data = RuntimeSettings.from_data(current.version, _deep_merge(before, patch)).data
    _validate_settings(data)
    latest = int((await session.execute(select(func.max(Setting.version)))).scalar_one() or 0)
    await session.execute(update(Setting).where(Setting.active).values(active=False))
    await session.flush()
    row = Setting(version=latest + 1, data=data, created_by=actor_id, active=True)
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor_id=actor_id,
        action="settings.update",
        target=f"settings:{row.version}",
        before=before,
        after=data,
    )
    return settings_out(row)


async def activate_settings(session: AsyncSession, *, actor_id: UUID, version: int) -> SettingsOut:
    await _lock_settings(session)
    target = (
        await session.execute(select(Setting).where(Setting.version == version).with_for_update())
    ).scalar_one_or_none()
    if target is None:
        raise _not_found("settings")
    before = {"version": version, "active": target.active}
    await session.execute(update(Setting).where(Setting.active).values(active=False))
    target.active = True
    await session.flush()
    _audit(
        session,
        actor_id=actor_id,
        action="settings.activate",
        target=f"settings:{version}",
        before=before,
        after={"version": version, "active": True},
    )
    return settings_out(target)


async def list_providers(session: AsyncSession) -> list[ProviderOut]:
    rows = (await session.execute(select(LlmProvider).order_by(LlmProvider.name))).scalars().all()
    return [_provider_out(row) for row in rows]


def _validate_base_url(value: str | None) -> None:
    if value is None:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError(
            "invalid_provider_url", "Provider URL must be an HTTP(S) URL", status_code=422
        )
    if (
        parsed.username
        or parsed.password
        or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    ):
        raise AppError(
            "invalid_provider_url", "Provider URL points to a forbidden host", status_code=422
        )


async def create_provider(
    session: AsyncSession, *, actor_id: UUID, body: ProviderCreate
) -> ProviderOut:
    if (
        await session.execute(select(LlmProvider).where(LlmProvider.name == body.name))
    ).scalar_one_or_none():
        raise AppError("provider_exists", "Provider already exists", status_code=409)
    _validate_base_url(body.base_url or None)
    row = LlmProvider(
        name=body.name,
        kind=body.kind,
        base_url=body.base_url or None,
        api_key_enc=encrypt_provider_key(body.api_key) if body.api_key else None,
        enabled=body.enabled,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        actor_id=actor_id,
        action="provider.create",
        target=f"provider:{row.id}",
        before=None,
        after=_provider_out(row).model_dump(mode="json"),
    )
    return _provider_out(row)


async def update_provider(
    session: AsyncSession, *, actor_id: UUID, provider_id: UUID, body: ProviderPatch
) -> ProviderOut:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise _not_found("provider")
    if "base_url" in body.model_fields_set:
        _validate_base_url(body.base_url)
    before = _provider_out(row).model_dump(mode="json")
    for field in ("name", "kind", "base_url", "enabled"):
        if field in body.model_fields_set:
            value = getattr(body, field)
            setattr(row, field, value)
    if "api_key" in body.model_fields_set:
        row.api_key_enc = encrypt_provider_key(body.api_key) if body.api_key else None
    await session.flush()
    after = _provider_out(row).model_dump(mode="json")
    _audit(
        session,
        actor_id=actor_id,
        action="provider.update",
        target=f"provider:{row.id}",
        before=before,
        after=after,
    )
    return _provider_out(row)


async def test_provider(session: AsyncSession, provider_id: UUID) -> dict[str, object]:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise _not_found("provider")
    if not row.api_key_enc or not row.base_url:
        raise AppError(
            "provider_not_configured", "Provider key and base URL are required", status_code=422
        )
    headers = {"Authorization": f"Bearer {decrypt_provider_key(row.api_key_enc)}"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{row.base_url.rstrip('/')}/models", headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AppError("provider_test_failed", "Provider test failed", status_code=502) from exc
    return {"ok": True, "status_code": response.status_code}


async def list_models(session: AsyncSession) -> list[AdminModelOut]:
    rows = (await session.execute(select(Model).order_by(Model.model_id))).scalars().all()
    return [_model_out(row) for row in rows]


async def create_model(
    session: AsyncSession, *, actor_id: UUID, body: ModelCreate
) -> AdminModelOut:
    if await session.get(LlmProvider, body.provider_id) is None:
        raise _not_found("provider")
    duplicate = (
        await session.execute(
            select(Model).where(
                Model.provider_id == body.provider_id, Model.model_id == body.model_id
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise AppError("model_exists", "Model already exists for this provider", status_code=409)
    row = Model(
        provider_id=body.provider_id,
        model_id=body.model_id,
        price_in=body.price_in,
        price_out=body.price_out,
        context_window=body.context_window,
        capabilities=body.capabilities,
        enabled=body.enabled,
    )
    session.add(row)
    await session.flush()
    after = _model_out(row).model_dump(mode="json")
    _audit(
        session,
        actor_id=actor_id,
        action="model.create",
        target=f"model:{row.id}",
        before=None,
        after=after,
    )
    return _model_out(row)


async def update_model(
    session: AsyncSession, *, actor_id: UUID, model_id: UUID, body: ModelPatch
) -> AdminModelOut:
    row = await session.get(Model, model_id)
    if row is None:
        raise _not_found("model")
    before = _model_out(row).model_dump(mode="json")
    for field in ("price_in", "price_out", "context_window", "capabilities", "enabled"):
        if field in body.model_fields_set:
            value = getattr(body, field)
            if field == "enabled" and value is None:
                raise AppError("invalid_model", "enabled cannot be null", status_code=422)
            setattr(row, field, value)
    await session.flush()
    after = _model_out(row).model_dump(mode="json")
    _audit(
        session,
        actor_id=actor_id,
        action="model.update",
        target=f"model:{row.id}",
        before=before,
        after=after,
    )
    return _model_out(row)


async def list_roles(session: AsyncSession) -> list[RoleOut]:
    rows = (await session.execute(select(ModelRole).order_by(ModelRole.role))).scalars().all()
    return [
        RoleOut(role=row.role, model_id=row.model_id, fallback_model_id=row.fallback_model_id)
        for row in rows
    ]


async def upsert_role(session: AsyncSession, *, actor_id: UUID, body: RoleUpsert) -> RoleOut:
    row = (
        await session.execute(
            select(ModelRole).where(ModelRole.role == body.role).with_for_update()
        )
    ).scalar_one_or_none()
    before = (
        None
        if row is None
        else {
            "role": row.role,
            "model_id": row.model_id,
            "fallback_model_id": row.fallback_model_id,
        }
    )
    if row is None:
        row = ModelRole(
            role=body.role, model_id=body.model_id, fallback_model_id=body.fallback_model_id
        )
        session.add(row)
    else:
        row.model_id = body.model_id
        row.fallback_model_id = body.fallback_model_id
    await session.flush()
    after = {"role": row.role, "model_id": row.model_id, "fallback_model_id": row.fallback_model_id}
    _audit(
        session,
        actor_id=actor_id,
        action="role.upsert",
        target=f"role:{row.role}",
        before=before,
        after=after,
    )
    return RoleOut(role=row.role, model_id=row.model_id, fallback_model_id=row.fallback_model_id)


async def list_plans(session: AsyncSession) -> list[PlanOut]:
    rows = (await session.execute(select(Plan).order_by(Plan.name))).scalars().all()
    return [
        PlanOut(
            id=row.id, name=row.name, credits_5h=row.credits_5h, credits_month=row.credits_month
        )
        for row in rows
    ]


async def create_plan(session: AsyncSession, *, actor_id: UUID, body: PlanCreate) -> PlanOut:
    if (await session.execute(select(Plan).where(Plan.name == body.name))).scalar_one_or_none():
        raise AppError("plan_exists", "Plan already exists", status_code=409)
    row = Plan(name=body.name, credits_5h=body.credits_5h, credits_month=body.credits_month)
    session.add(row)
    await session.flush()
    after = {
        "id": str(row.id),
        "name": row.name,
        "credits_5h": row.credits_5h,
        "credits_month": row.credits_month,
    }
    _audit(
        session,
        actor_id=actor_id,
        action="plan.create",
        target=f"plan:{row.id}",
        before=None,
        after=after,
    )
    return PlanOut(
        id=row.id, name=row.name, credits_5h=row.credits_5h, credits_month=row.credits_month
    )


async def update_plan(
    session: AsyncSession, *, actor_id: UUID, plan_id: UUID, body: PlanPatch
) -> PlanOut:
    row = await session.get(Plan, plan_id)
    if row is None:
        raise _not_found("plan")
    before = {
        "id": str(row.id),
        "name": row.name,
        "credits_5h": row.credits_5h,
        "credits_month": row.credits_month,
    }
    for field in ("name", "credits_5h", "credits_month"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    await session.flush()
    after = {
        "id": str(row.id),
        "name": row.name,
        "credits_5h": row.credits_5h,
        "credits_month": row.credits_month,
    }
    _audit(
        session,
        actor_id=actor_id,
        action="plan.update",
        target=f"plan:{row.id}",
        before=before,
        after=after,
    )
    return PlanOut(
        id=row.id, name=row.name, credits_5h=row.credits_5h, credits_month=row.credits_month
    )


async def list_users(session: AsyncSession) -> list[UserOut]:
    rows = (
        await session.execute(
            select(User, UserQuotaOverride)
            .join(UserQuotaOverride, UserQuotaOverride.user_id == User.id, isouter=True)
            .order_by(User.created_at.desc())
        )
    ).all()
    return [_user_out(user, override) for user, override in rows]


def _user_out(user: User, override: UserQuotaOverride | None) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        plan_id=user.plan_id,
        credits_5h=override.credits_5h if override else None,
        credits_month=override.credits_month if override else None,
    )


async def update_user(
    session: AsyncSession, *, actor_id: UUID, user_id: UUID, body: UserPatch
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise _not_found("user")
    override = await session.get(UserQuotaOverride, user_id)
    before = _user_out(user, override).model_dump(mode="json")
    for field in ("role", "status", "plan_id"):
        if field in body.model_fields_set:
            value = getattr(body, field)
            if value is None:
                raise AppError("invalid_user", f"{field} cannot be null", status_code=422)
            setattr(user, field, value)
    if "credits_5h" in body.model_fields_set or "credits_month" in body.model_fields_set:
        override = override or UserQuotaOverride(user_id=user_id)
        if "credits_5h" in body.model_fields_set:
            override.credits_5h = body.credits_5h
        if "credits_month" in body.model_fields_set:
            override.credits_month = body.credits_month
        session.add(override)
    await session.flush()
    after = _user_out(user, override).model_dump(mode="json")
    _audit(
        session,
        actor_id=actor_id,
        action="user.update",
        target=f"user:{user.id}",
        before=before,
        after=after,
    )
    return _user_out(user, override)


async def list_audit(session: AsyncSession, *, limit: int = 100) -> list[AuditOut]:
    rows = (
        (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        AuditOut(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            target=row.target,
            before=row.before,
            after=row.after,
            created_at=row.created_at,
        )
        for row in rows
    ]
