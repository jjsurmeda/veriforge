from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.ids import uuid7
from db.models import Chat, Message, Plan, Run, UsageLedger, User
from db.session import get_session_factory
from quota.service import (
    QuotaExceeded,
    UsageSnapshot,
    calculate_credits,
    gate_and_reserve,
    quota_summary,
    settle_run,
)


async def _user_and_runs(
    db: AsyncSession, *, credits_5h: int = 100, credits_month: int = 100, count: int = 2
) -> tuple[User, list[UUID]]:
    plan = Plan(name=f"quota-{uuid7().hex[:8]}", credits_5h=credits_5h, credits_month=credits_month)
    user = User(email=f"quota-{uuid7().hex[:8]}@test.dev", role="user", plan_id=plan.id)
    db.add(plan)
    await db.flush()
    user.plan_id = plan.id
    db.add(user)
    await db.flush()
    chat = Chat(user_id=user.id, title="quota")
    db.add(chat)
    await db.flush()
    run_ids: list[UUID] = []
    for _ in range(count):
        message = Message(chat_id=chat.id, role="assistant", content="", status=None)
        db.add(message)
        await db.flush()
        run = Run(message_id=message.id, mode="fast", source="auto", status="running")
        db.add(run)
        await db.flush()
        run_ids.append(run.id)
    await db.commit()
    return user, run_ids


def test_calculate_credits_uses_input_and_output_prices() -> None:
    assert (
        calculate_credits(
            price_in=2.0,
            price_out=4.0,
            reference_price=1.0,
            tokens_in=100,
            tokens_out=50,
        )
        == 400.0
    )


async def test_reservation_is_atomic_for_concurrent_runs(db: AsyncSession) -> None:
    user, run_ids = await _user_and_runs(db, credits_5h=100, credits_month=100)
    factory = get_session_factory()

    async def reserve(run_id: UUID) -> str:
        async with factory() as session, session.begin():
            try:
                await gate_and_reserve(
                    session,
                    user_id=user.id,
                    run_id=run_id,
                    mode="fast",
                    settings={"quota_estimates": {"fast": 60}},
                )
            except QuotaExceeded:
                return "rejected"
        return "accepted"

    results = await asyncio.gather(*(reserve(run_id) for run_id in run_ids))
    assert results.count("accepted") == 1
    assert results.count("rejected") == 1

    rows = (
        (
            await db.execute(
                select(UsageLedger).where(
                    UsageLedger.user_id == user.id,
                    UsageLedger.run_id.in_(run_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "reserved"
    assert rows[0].credits == 60


async def test_settlement_replaces_reservation_with_actual_once(db: AsyncSession) -> None:
    user, run_ids = await _user_and_runs(db, credits_5h=100, credits_month=100, count=1)
    reservation = await gate_and_reserve(
        db,
        user_id=user.id,
        run_id=run_ids[0],
        mode="fast",
        settings={"quota_estimates": {"fast": 80}},
    )
    await db.commit()

    snapshot = UsageSnapshot(model="test/model", role="run", tokens_in=10, tokens_out=5, credits=25)
    await settle_run(db, reservation.run_id, snapshot)
    await settle_run(db, reservation.run_id, snapshot)
    await db.commit()

    row = (
        await db.execute(select(UsageLedger).where(UsageLedger.run_id == reservation.run_id))
    ).scalar_one()
    assert row.status == "settled"
    assert row.credits == 25
    assert row.tokens_in == 10
    assert row.tokens_out == 5


async def test_quota_summary_reports_both_windows_and_resets(db: AsyncSession) -> None:
    user, run_ids = await _user_and_runs(db, credits_5h=100, credits_month=100, count=1)
    await gate_and_reserve(
        db,
        user_id=user.id,
        run_id=run_ids[0],
        mode="fast",
        settings={"quota_estimates": {"fast": 40}},
    )
    await db.commit()

    summary = await quota_summary(
        db,
        user_id=user.id,
        mode="fast",
        settings={"quota_estimates": {"fast": 40}},
    )
    assert summary.used_5h == 40
    assert summary.used_month == 40
    assert summary.remaining_5h == 60
    assert summary.remaining_month == 60
    assert summary.reset_at_5h > datetime.now(UTC)
    assert summary.reset_at_month > datetime.now(UTC)
    assert summary.blocked is False


async def test_quota_summary_marks_over_limit(db: AsyncSession) -> None:
    user, run_ids = await _user_and_runs(db, credits_5h=10, credits_month=10, count=1)
    with pytest.raises(QuotaExceeded) as raised:
        await gate_and_reserve(
            db,
            user_id=user.id,
            run_id=run_ids[0],
            mode="deep",
            settings={"quota_estimates": {"deep": 30}},
        )
    await db.rollback()
    assert raised.value.status_code == 429
    assert raised.value.detail is not None
    detail = raised.value.detail
    assert isinstance(detail, dict)
    assert "reset_at" in detail
