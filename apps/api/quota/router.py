from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.session import get_session
from quota.service import quota_summary
from runtime import load_active_runtime
from schemas.quota import QuotaOut

router = APIRouter(tags=["quota"])


@router.get("/me/quota", response_model=QuotaOut)
async def get_quota(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    mode: Annotated[str, Query(pattern="^(fast|auto|deep)$")] = "auto",
) -> QuotaOut:
    settings = await load_active_runtime(session)
    summary = await quota_summary(session, user_id=user.id, mode=mode, settings=settings.data)
    return QuotaOut(
        mode=mode,
        used_5h=summary.used_5h,
        used_month=summary.used_month,
        limit_5h=summary.limit_5h,
        limit_month=summary.limit_month,
        remaining_5h=summary.remaining_5h,
        remaining_month=summary.remaining_month,
        reset_at_5h=summary.reset_at_5h,
        reset_at_month=summary.reset_at_month,
        estimate=summary.estimate,
        blocked=summary.blocked,
    )
