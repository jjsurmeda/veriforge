from typing import Any

from pydantic import BaseModel


class ModelOut(BaseModel):
    model_id: str
    provider: str
    price_in: float | None
    price_out: float | None
    context_window: int | None
    capabilities: dict[str, Any] | None
    enabled: bool


class ModelRoleOut(BaseModel):
    role: str
    model_id: str
    fallback_model_id: str | None
