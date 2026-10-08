from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import invites
from db.models import (
    AuditLog,
    Invite,
    LlmProvider,
    Model,
    ModelRole,
    Plan,
    Setting,
    User,
    UserQuotaOverride,
)
from decisions.breaker import get_breaker
from errors import AppError
from netguard import BlockedAddress, assert_public_url
from providers.credentials import decrypt_provider_key, encrypt_provider_key
from runtime import RuntimeSettings
from schemas.admin import (
    AdminModelOut,
    AuditOut,
    DecisionBreakerOut,
    DecisionCountOut,
    DecisionShadowDisagreementOut,
    DecisionShadowOut,
    DecisionStatsOut,
    DecisionTargetsOut,
    InviteCreate,
    InviteOut,
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
    "generation",
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
    generation = data.get("generation", {})
    if not isinstance(generation, dict):
        raise AppError("invalid_settings", "Generation settings must be an object", status_code=422)
    temperature = generation.get("temperature")
    # `None` is meaningful, not absent: it means "send no temperature", so it
    # passes. A number must be in [0, 2], the range every provider we use
    # accepts (gpt-4o-mini and the Nemotron models reject anything above 2).
    if temperature is not None and (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= temperature <= 2
    ):
        raise AppError(
            "invalid_settings",
            "generation.temperature must be null or a number between 0 and 2",
            status_code=422,
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


async def _validate_base_url(value: str | None) -> None:
    """Reject a base URL we must never send a provider credential to.

    A literal host name is not the check: an attacker-chosen name can resolve
    to RFC1918, link-local or the cloud metadata address, and the same policy
    the web fetcher uses is the one that has to hold here (review S4).
    """
    if value is None:
        return
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AppError(
            "invalid_provider_url", "Provider URL must be an HTTP(S) URL", status_code=422
        )
    try:
        await assert_public_url(value)
    except BlockedAddress as exc:
        raise AppError(
            "invalid_provider_url", f"Provider URL is not a public address: {exc}", status_code=422
        ) from exc


async def create_provider(
    session: AsyncSession, *, actor_id: UUID, body: ProviderCreate
) -> ProviderOut:
    if (
        await session.execute(select(LlmProvider).where(LlmProvider.name == body.name))
    ).scalar_one_or_none():
        raise AppError("provider_exists", "Provider already exists", status_code=409)
    await _validate_base_url(body.base_url or None)
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
        await _validate_base_url(body.base_url)
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
    url = f"{row.base_url.rstrip('/')}/models"
    # Re-check the resolved address here, not only at write time: DNS can
    # change under a stored base URL, and this is the request that carries the
    # decrypted credential (review S4).
    try:
        await assert_public_url(url)
    except BlockedAddress as exc:
        raise AppError(
            "invalid_provider_url", f"Provider URL is not a public address: {exc}", status_code=422
        ) from exc
    headers = {"Authorization": f"Bearer {decrypt_provider_key(row.api_key_enc)}"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, headers=headers)
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


def _shadow_answer(answer: dict[str, object]) -> dict[str, object]:
    return {key: answer[key] for key in ("value", "probability", "probabilities") if key in answer}


async def decision_stats(session: AsyncSession, *, hours: int = 24) -> DecisionStatsOut:
    window = max(1, min(168, hours))
    cutoff = datetime.now(UTC) - timedelta(hours=window)
    totals = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE re.payload->>'engine' = 'jev') AS jev_count,
                    COUNT(*) FILTER (WHERE re.payload->>'engine' = 'fallback') AS fallback_count
                FROM run_events AS re
                JOIN runs AS r ON r.id = re.run_id
                WHERE re.type = 'decision' AND re.created_at >= :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().one()
    call_latency = (
        await session.execute(
            text(
                """
                WITH decision_events AS (
                    SELECT
                        re.run_id,
                        re.seq,
                        COALESCE(
                            NULLIF(re.payload->>'call_id', ''),
                            re.run_id::text || ':' || re.seq::text
                        ) AS call_key,
                        (re.payload->>'latency_ms')::double precision AS latency_ms,
                        re.payload->>'engine' AS engine,
                        re.payload->>'stage' AS stage
                    FROM run_events AS re
                    JOIN runs AS r ON r.id = re.run_id
                    WHERE re.type = 'decision' AND re.created_at >= :cutoff
                ), calls AS (
                    SELECT
                        run_id,
                        call_key,
                        MAX(latency_ms) AS latency_ms,
                        BOOL_OR(engine = 'jev') AS is_jev,
                        BOOL_OR(stage = 'ingress') AS is_ingress
                    FROM decision_events
                    GROUP BY run_id, call_key
                )
                SELECT
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
                        FILTER (WHERE is_jev) AS jev_p50,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                        FILTER (WHERE is_jev) AS jev_p95,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                        FILTER (WHERE is_ingress) AS ingress_p95
                FROM calls
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().one()
    # Lane E item 3: the reranker's own latency, which the showcase's decision
    # view reports alongside Jev's. Read from the `rerank` step events rather
    # than the decision events: reranking is not a DecisionEngine call, it is
    # the provider's rerank endpoint, and its cost was in no statistic here at
    # all before this.
    rerank_latency = (
        await session.execute(
            text(
                """
                SELECT
                    percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY (re.payload->>'duration_ms')::double precision
                    ) AS rerank_p50,
                    percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY (re.payload->>'duration_ms')::double precision
                    ) AS rerank_p95
                FROM run_events AS re
                JOIN runs AS r ON r.id = re.run_id
                WHERE re.type = 'step.completed'
                    AND re.created_at >= :cutoff
                    AND re.payload->>'node' = 'rerank'
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().one()
    by_decision_rows = (
        await session.execute(
            text(
                """
                SELECT
                    CASE
                        WHEN re.payload->>'name' LIKE 'chunk_injection_%'
                            THEN 'chunk_injection_*'
                        WHEN re.payload->>'stage' = 'claim_verdict'
                            OR re.payload->>'name' LIKE 'claim_%'
                            THEN 'claim_verdicts'
                        -- One Noul per passage for the entity gate, one per
                        -- candidate pair for the conflict check, and one per
                        -- passage for JevRerank's relevance scoring. Each is
                        -- ONE check whose name happens to be numbered, so
                        -- listing every index turned this table into a wall of
                        -- `passage_7` rows that told an operator nothing. The
                        -- trace's gate card shows these families per run with
                        -- their real values; here they are a count.
                        WHEN re.payload->>'name' LIKE 'entity_%'
                            THEN 'entity_match'
                        WHEN re.payload->>'name' LIKE 'conflict_%'
                            THEN 'conflict_pairs'
                        WHEN re.payload->>'name' LIKE 'passage_%'
                            THEN 'passage_relevance'
                        ELSE re.payload->>'name'
                    END AS name_or_prefix,
                    COUNT(*) AS count,
                    COUNT(*) FILTER (WHERE re.payload->>'engine' = 'fallback') AS fallback_count
                FROM run_events AS re
                JOIN runs AS r ON r.id = re.run_id
                WHERE re.type = 'decision' AND re.created_at >= :cutoff
                GROUP BY 1
                ORDER BY count DESC, name_or_prefix
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().all()
    shadow_totals = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS sampled,
                    AVG(CASE WHEN agree THEN 1.0 ELSE 0.0 END) AS agree_rate
                FROM decision_shadow
                WHERE created_at >= :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().one()
    disagreements = (
        await session.execute(
            text(
                """
                SELECT run_id, decision, jev_answer, fallback_answer, created_at
                FROM decision_shadow
                WHERE created_at >= :cutoff AND NOT agree
                ORDER BY created_at DESC
                LIMIT 20
                """
            ),
            {"cutoff": cutoff},
        )
    ).mappings().all()

    total = int(totals["total"])
    fallback_count = int(totals["fallback_count"])
    sampled = int(shadow_totals["sampled"])
    breaker = get_breaker()
    breaker_state = {
        "closed": "closed",
        "open": "open",
        "probing": "half_open",
    }[breaker.state.value]
    return DecisionStatsOut(
        total=total,
        jev_count=int(totals["jev_count"]),
        fallback_count=fallback_count,
        fallback_share=fallback_count / total if total else 0.0,
        jev_latency_p50_ms=call_latency["jev_p50"],
        jev_latency_p95_ms=call_latency["jev_p95"],
        ingress_p95_ms=call_latency["ingress_p95"],
        by_decision=[
            DecisionCountOut(
                name_or_prefix=row["name_or_prefix"],
                count=int(row["count"]),
                fallback_count=int(row["fallback_count"]),
            )
            for row in by_decision_rows
        ],
        rerank_latency_p50_ms=rerank_latency["rerank_p50"],
        rerank_latency_p95_ms=rerank_latency["rerank_p95"],
        breaker=DecisionBreakerOut(state=breaker_state, open_until=breaker.open_until),
        shadow=DecisionShadowOut(
            sampled=sampled,
            agree_rate=float(shadow_totals["agree_rate"] or 0.0),
            recent_disagreements=[
                DecisionShadowDisagreementOut(
                    run_id=row["run_id"],
                    decision=row["decision"],
                    jev_answer=_shadow_answer(row["jev_answer"]),
                    fallback_answer=_shadow_answer(row["fallback_answer"]),
                    created_at=row["created_at"],
                )
                for row in disagreements
            ],
        ),
        targets=DecisionTargetsOut(ingress_p95_ms=600, fallback_share=0.05),
    )


# --- invites (item 4) -----------------------------------------------------
#
# Thin CRUD over `auth/invites.py`, with the audit rows every other admin
# action here writes. The business rules live in the auth package because
# `auth/router.py` needs them too, and python.md's dependency direction says
# admin depends on auth — not the other way round.


async def create_invites(
    session: AsyncSession, *, actor_id: UUID, body: InviteCreate
) -> list[InviteOut]:
    created = await invites.create(
        session,
        actor_id=actor_id,
        count=body.count,
        expires_in_days=body.expires_in_days,
        note=body.note,
    )
    # The audit row carries the note, the count and the expiry — never the
    # code. A code in `audit_log` would be a credential in the one table
    # every admin can read forever, which is precisely what storing the hash
    # was to avoid.
    _audit(
        session,
        actor_id=actor_id,
        action="invite.create",
        target=f"invites:{len(created)}",
        before=None,
        after={
            "count": body.count,
            "expires_in_days": body.expires_in_days,
            "note": body.note,
            "ids": [str(invite.id) for invite, _ in created],
        },
    )
    return [
        InviteOut(**invites.invite_out(invite, code=code))
        for invite, code in created
    ]


async def list_invites(session: AsyncSession, *, status: str | None) -> list[InviteOut]:
    rows = await invites.list_all(session, status=status)
    # No `code=` here: this is a later read, and the plaintext is gone. An
    # admin who needs the code again mints another one.
    return [InviteOut(**invites.invite_out(row)) for row in rows]


async def revoke_invite(
    session: AsyncSession, *, actor_id: UUID, invite_id: UUID
) -> InviteOut:
    before_status = None
    existing = await session.get(Invite, invite_id)
    if existing is not None:
        before_status = invites.status_of(existing)
    invite = await invites.revoke(session, invite_id=invite_id)
    _audit(
        session,
        actor_id=actor_id,
        action="invite.revoke",
        target=f"invite:{invite_id}",
        before={"status": before_status},
        after={"status": invites.status_of(invite)},
    )
    return InviteOut(**invites.invite_out(invite))
