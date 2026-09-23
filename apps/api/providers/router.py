"""Model catalogue read endpoints (CH-8): the picker reads these;
administrators use the separate /admin catalogue routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.models import LlmProvider, Model, ModelRole
from db.session import get_session
from schemas.models import ModelOut, ModelRoleOut

router = APIRouter(tags=["models"])


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ModelOut]:
    rows = (
        await session.execute(
            select(Model, LlmProvider)
            .join(LlmProvider, Model.provider_id == LlmProvider.id)
            .where(Model.enabled, LlmProvider.enabled)
            .order_by(Model.model_id)
        )
    ).all()
    return [
        ModelOut(
            model_id=model.model_id,
            provider=provider.name,
            price_in=float(model.price_in) if model.price_in is not None else None,
            price_out=float(model.price_out) if model.price_out is not None else None,
            context_window=model.context_window,
            capabilities=model.capabilities,
            enabled=model.enabled,
        )
        for model, provider in rows
        if not (model.capabilities or {}).get("decision", False)
    ]


@router.get("/model-roles", response_model=list[ModelRoleOut])
async def list_model_roles(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ModelRoleOut]:
    roles = (
        await session.execute(select(ModelRole).order_by(ModelRole.role))
    ).scalars().all()
    return [
        ModelRoleOut(role=r.role, model_id=r.model_id, fallback_model_id=r.fallback_model_id)
        for r in roles
    ]
