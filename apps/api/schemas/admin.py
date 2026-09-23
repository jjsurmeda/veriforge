from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    base_url: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool = True


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    kind: str | None = Field(default=None, min_length=1, max_length=32)
    base_url: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class ProviderOut(BaseModel):
    id: UUID
    name: str
    kind: str
    base_url: str | None
    enabled: bool
    has_api_key: bool


class ModelCreate(BaseModel):
    provider_id: UUID
    model_id: str = Field(min_length=1, max_length=128)
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, ge=1)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ModelPatch(BaseModel):
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, ge=1)
    capabilities: dict[str, Any] | None = None
    enabled: bool | None = None


class AdminModelOut(BaseModel):
    id: UUID
    provider_id: UUID
    model_id: str
    price_in: float | None
    price_out: float | None
    context_window: int | None
    capabilities: dict[str, Any] | None
    enabled: bool


class RoleUpsert(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    model_id: str = Field(min_length=1, max_length=128)
    fallback_model_id: str | None = Field(default=None, max_length=128)


class RoleOut(BaseModel):
    role: str
    model_id: str
    fallback_model_id: str | None


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    credits_5h: int = Field(ge=0)
    credits_month: int = Field(ge=0)


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    credits_5h: int | None = Field(default=None, ge=0)
    credits_month: int | None = Field(default=None, ge=0)


class PlanOut(BaseModel):
    id: UUID
    name: str
    credits_5h: int
    credits_month: int


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin|demo)$")
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    plan_id: UUID | None = None
    credits_5h: int | None = Field(default=None, ge=0)
    credits_month: int | None = Field(default=None, ge=0)


class UserOut(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    plan_id: UUID
    credits_5h: int | None
    credits_month: int | None


class SettingsOut(BaseModel):
    version: int
    data: dict[str, Any]
    active: bool
    created_at: datetime


class AuditOut(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    target: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime
