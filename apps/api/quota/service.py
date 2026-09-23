from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan, UsageLedger, User, UserQuotaOverride
from errors import AppError

DEFAULT_ESTIMATES = {"fast": 3_000, "auto": 8_000, "deep": 30_000}


class QuotaExceeded(AppError):
    status_code = 429


@dataclass(frozen=True)
class UsageSnapshot:
    model: str
    role: str
    tokens_in: int
    tokens_out: int
    credits: float


@dataclass(frozen=True)
class QuotaReservation:
    id: UUID
    run_id: UUID
    user_id: UUID
    estimate: int
    remaining_5h: float
    remaining_month: float


@dataclass(frozen=True)
class QuotaSummary:
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


def calculate_credits(
    *, price_in: float, price_out: float, reference_price: float, tokens_in: int, tokens_out: int
) -> float:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    return (price_in * tokens_in + price_out * tokens_out) / reference_price


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: datetime) -> datetime:
    start = _month_start(now)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def _estimate(mode: str, settings: dict[str, Any] | None) -> int:
    values = (settings or {}).get("quota_estimates", {})
    value = values.get(mode, DEFAULT_ESTIMATES.get(mode, 0)) if isinstance(values, dict) else 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_ESTIMATES.get(mode, 0)


async def _limits(session: AsyncSession, user_id: UUID, *, lock: bool) -> tuple[User, int, int]:
    statement = select(User).where(User.id == user_id)
    if lock:
        statement = statement.with_for_update()
    user = (await session.execute(statement)).scalar_one_or_none()
    if user is None:
        raise AppError("user_not_found", "User not found", status_code=404)
    plan = await session.get(Plan, user.plan_id)
    if plan is None:
        raise AppError("plan_not_found", "User plan not found", status_code=500)
    override = await session.get(UserQuotaOverride, user_id)
    limit_5h = (
        override.credits_5h if override and override.credits_5h is not None else plan.credits_5h
    )
    limit_month = (
        override.credits_month
        if override and override.credits_month is not None
        else plan.credits_month
    )
    return user, int(limit_5h), int(limit_month)


async def _window_usage(
    session: AsyncSession, user_id: UUID, now: datetime
) -> tuple[float, float, datetime | None]:
    five_start = now - timedelta(hours=5)
    month_start = _month_start(now)
    five = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.credits), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.ts >= five_start,
            UsageLedger.ts <= now,
        )
    )
    month = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.credits), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.ts >= month_start,
            UsageLedger.ts <= now,
        )
    )
    oldest = await session.scalar(
        select(func.min(UsageLedger.ts)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.ts >= five_start,
            UsageLedger.ts <= now,
        )
    )
    return float(five or 0), float(month or 0), oldest


def _blocked_detail(
    *,
    used_5h: float,
    used_month: float,
    limit_5h: int,
    limit_month: int,
    estimate: int,
    oldest: datetime | None,
    now: datetime,
) -> tuple[datetime, str]:
    reset_5h = oldest + timedelta(hours=5) if oldest is not None else now + timedelta(hours=5)
    reset_month = _next_month(now)
    if used_5h + estimate > limit_5h and used_month + estimate > limit_month:
        return min(reset_5h, reset_month), "both"
    if used_5h + estimate > limit_5h:
        return reset_5h, "5h"
    return reset_month, "month"


async def gate_and_reserve(
    session: AsyncSession,
    *,
    user_id: UUID,
    run_id: UUID,
    mode: str,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> QuotaReservation:
    _, limit_5h, limit_month = await _limits(session, user_id, lock=True)
    current = now or datetime.now(UTC)
    used_5h, used_month, oldest = await _window_usage(session, user_id, current)
    estimate = _estimate(mode, settings)
    if used_5h + estimate > limit_5h or used_month + estimate > limit_month:
        reset_at, window = _blocked_detail(
            used_5h=used_5h,
            used_month=used_month,
            limit_5h=limit_5h,
            limit_month=limit_month,
            estimate=estimate,
            oldest=oldest,
            now=current,
        )
        raise QuotaExceeded(
            "quota_exceeded",
            "Your credit limit has been reached for this window",
            {"reset_at": reset_at.isoformat(), "window": window},
        )
    row = UsageLedger(
        user_id=user_id,
        run_id=run_id,
        model="aggregate",
        role="run",
        tokens_in=0,
        tokens_out=0,
        credits=estimate,
        status="reserved",
        ts=current,
    )
    session.add(row)
    await session.flush()
    return QuotaReservation(
        id=row.id,
        run_id=run_id,
        user_id=user_id,
        estimate=estimate,
        remaining_5h=max(0.0, limit_5h - used_5h - estimate),
        remaining_month=max(0.0, limit_month - used_month - estimate),
    )


async def settle_run(
    session: AsyncSession, run_id: UUID, snapshot: UsageSnapshot | None
) -> None:
    row = (
        await session.execute(
            select(UsageLedger)
            .where(UsageLedger.run_id == run_id, UsageLedger.status == "reserved")
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return
    if snapshot is not None:
        row.model = snapshot.model
        row.role = snapshot.role
        row.tokens_in = snapshot.tokens_in
        row.tokens_out = snapshot.tokens_out
        row.credits = snapshot.credits
    row.status = "settled"
    await session.flush()


async def quota_summary(
    session: AsyncSession,
    *,
    user_id: UUID,
    mode: str = "auto",
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> QuotaSummary:
    current = now or datetime.now(UTC)
    _, limit_5h, limit_month = await _limits(session, user_id, lock=False)
    used_5h, used_month, oldest = await _window_usage(session, user_id, current)
    estimate = _estimate(mode, settings)
    remaining_5h = max(0.0, limit_5h - used_5h)
    remaining_month = max(0.0, limit_month - used_month)
    return QuotaSummary(
        used_5h=used_5h,
        used_month=used_month,
        limit_5h=limit_5h,
        limit_month=limit_month,
        remaining_5h=remaining_5h,
        remaining_month=remaining_month,
        reset_at_5h=oldest + timedelta(hours=5)
        if oldest is not None
        else current + timedelta(hours=5),
        reset_at_month=_next_month(current),
        estimate=estimate,
        blocked=used_5h + estimate > limit_5h or used_month + estimate > limit_month,
    )
