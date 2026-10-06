from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Query

from admin import service
from auth.deps import AdminUser
from db.session import SessionDep
from schemas.admin import (
    AdminModelOut,
    AuditOut,
    DecisionStatsOut,
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

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/providers", response_model=list[ProviderOut])
async def providers(
    _: AdminUser,
    session: SessionDep,
) -> list[ProviderOut]:
    return await service.list_providers(session)


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(
    body: ProviderCreate,
    user: AdminUser,
    session: SessionDep,
) -> ProviderOut:
    return await service.create_provider(session, actor_id=user.id, body=body)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: UUID,
    body: ProviderPatch,
    user: AdminUser,
    session: SessionDep,
) -> ProviderOut:
    return await service.update_provider(
        session, actor_id=user.id, provider_id=provider_id, body=body
    )


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: UUID,
    _: AdminUser,
    session: SessionDep,
) -> dict[str, object]:
    return await service.test_provider(session, provider_id)


@router.get("/models", response_model=list[AdminModelOut])
async def models(
    _: AdminUser,
    session: SessionDep,
) -> list[AdminModelOut]:
    return await service.list_models(session)


@router.post("/models", response_model=AdminModelOut, status_code=201)
async def create_model(
    body: ModelCreate,
    user: AdminUser,
    session: SessionDep,
) -> AdminModelOut:
    return await service.create_model(session, actor_id=user.id, body=body)


@router.patch("/models/{model_id}", response_model=AdminModelOut)
async def update_model(
    model_id: UUID,
    body: ModelPatch,
    user: AdminUser,
    session: SessionDep,
) -> AdminModelOut:
    return await service.update_model(session, actor_id=user.id, model_id=model_id, body=body)


@router.get("/roles", response_model=list[RoleOut])
async def roles(
    _: AdminUser,
    session: SessionDep,
) -> list[RoleOut]:
    return await service.list_roles(session)


@router.post("/roles", response_model=RoleOut)
async def upsert_role(
    body: RoleUpsert,
    user: AdminUser,
    session: SessionDep,
) -> RoleOut:
    return await service.upsert_role(session, actor_id=user.id, body=body)


@router.get("/plans", response_model=list[PlanOut])
async def plans(
    _: AdminUser,
    session: SessionDep,
) -> list[PlanOut]:
    return await service.list_plans(session)


@router.post("/plans", response_model=PlanOut, status_code=201)
async def create_plan(
    body: PlanCreate,
    user: AdminUser,
    session: SessionDep,
) -> PlanOut:
    return await service.create_plan(session, actor_id=user.id, body=body)


@router.patch("/plans/{plan_id}", response_model=PlanOut)
async def update_plan(
    plan_id: UUID,
    body: PlanPatch,
    user: AdminUser,
    session: SessionDep,
) -> PlanOut:
    return await service.update_plan(session, actor_id=user.id, plan_id=plan_id, body=body)


@router.get("/users", response_model=list[UserOut])
async def users(
    _: AdminUser,
    session: SessionDep,
) -> list[UserOut]:
    return await service.list_users(session)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UserPatch,
    user: AdminUser,
    session: SessionDep,
) -> UserOut:
    return await service.update_user(session, actor_id=user.id, user_id=user_id, body=body)


@router.get("/settings", response_model=SettingsOut)
async def active_settings(
    _: AdminUser,
    session: SessionDep,
) -> SettingsOut:
    row = await service.get_settings_row(session, lock=True)
    return service.settings_out(row)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    user: AdminUser,
    session: SessionDep,
    data: Annotated[dict[str, Any], Body()],
) -> SettingsOut:
    return await service.update_settings(session, actor_id=user.id, patch=data)


@router.get("/settings/versions", response_model=list[SettingsOut])
async def settings_versions(
    _: AdminUser,
    session: SessionDep,
) -> list[SettingsOut]:
    return await service.list_settings(session)


@router.post("/settings/{version}/activate", response_model=SettingsOut)
async def activate_settings(
    version: int,
    user: AdminUser,
    session: SessionDep,
) -> SettingsOut:
    return await service.activate_settings(session, actor_id=user.id, version=version)


@router.get("/decisions/stats", response_model=DecisionStatsOut)
async def decision_stats(
    _: AdminUser,
    session: SessionDep,
    hours: Annotated[int, Query()] = 24,
) -> DecisionStatsOut:
    return await service.decision_stats(session, hours=hours)


@router.get("/audit", response_model=list[AuditOut])
async def audit(
    _: AdminUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditOut]:
    return await service.list_audit(session, limit=limit)


# --- invites (item 4) -----------------------------------------------------
#
# Admin-only, audited like every other admin action, and there is
# deliberately no unauthenticated counterpart: an endpoint that can mint an
# account without a credential is the attack surface item 4 exists to close.


@router.post("/invites", response_model=list[InviteOut], status_code=201)
async def create_invites(
    body: InviteCreate,
    user: AdminUser,
    session: SessionDep,
) -> list[InviteOut]:
    return await service.create_invites(session, actor_id=user.id, body=body)


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(
    _: AdminUser,
    session: SessionDep,
    status: Annotated[str | None, Query()] = None,
) -> list[InviteOut]:
    return await service.list_invites(session, status=status)


@router.post("/invites/{invite_id}/revoke", response_model=InviteOut)
async def revoke_invite(
    invite_id: UUID,
    user: AdminUser,
    session: SessionDep,
) -> InviteOut:
    return await service.revoke_invite(session, actor_id=user.id, invite_id=invite_id)
