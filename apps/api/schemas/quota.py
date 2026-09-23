from datetime import datetime

from pydantic import BaseModel, Field


class QuotaOut(BaseModel):
    mode: str = Field(pattern="^(fast|auto|deep)$")
    used_5h: float
    used_month: float
    limit_5h: int
    limit_month: int
    remaining_5h: float
    remaining_month: float
    reset_at_5h: datetime
    reset_at_month: datetime
    estimate: int
    blocked: bool
