from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message, Plan, Run, UsageLedger, User
from db.session import get_session_factory
from quota.service import gate_and_reserve
from quota.usage import UsageContext, set_usage_context


async def _run(db: AsyncSession) -> tuple[User, UUID]:
    plan = Plan(name=f"usage-{id(db)}", credits_5h=100, credits_month=100)
    user = User(email=f"usage-{id(db)}@test.dev", role="user", plan_id=plan.id)
    db.add(plan)
    await db.flush()
    user.plan_id = plan.id
    db.add(user)
    await db.flush()
    chat = Chat(user_id=user.id, title="usage")
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.flush()
    run = Run(message_id=message.id, status="running")
    db.add(run)
    await db.flush()
    await db.commit()
    return user, run.id


async def test_usage_context_uses_catalogue_prices(db: AsyncSession) -> None:
    user, run_id = await _run(db)
    context = UsageContext(
        session_factory=get_session_factory(),
        user_id=user.id,
        run_id=run_id,
        model_roles={},
    )

    await context.record_call(
        model_id="openai/gpt-4o-mini", role="generator", tokens_in=100, tokens_out=50
    )

    snapshot = context.snapshot()
    assert snapshot.tokens_in == 100
    assert snapshot.tokens_out == 50
    assert snapshot.credits == 45.0


async def test_usage_context_accumulates_all_calls_and_exposes_budget(db: AsyncSession) -> None:
    user, run_id = await _run(db)
    context = UsageContext(
        session_factory=get_session_factory(),
        user_id=user.id,
        run_id=run_id,
        model_roles={"rewriter": "anthropic/claude-haiku-4.5"},
    )

    await context.record_call(model_id="ignored", role="rewriter", tokens_in=10, tokens_out=2)
    await context.record_call(
        model_id="openai/gpt-4o-mini", role="generator", tokens_in=20, tokens_out=5
    )

    assert context.tokens_in == 30
    assert context.tokens_out == 7
    assert context.credits == 26.0
    assert context.snapshot().credits == 26.0


async def test_usage_context_updates_reserved_ledger(db: AsyncSession) -> None:
    user, run_id = await _run(db)
    await gate_and_reserve(
        db,
        user_id=user.id,
        run_id=run_id,
        mode="fast",
        settings={"quota_estimates": {"fast": 100}},
    )
    await db.commit()
    context = UsageContext(get_session_factory(), user.id, run_id, {})

    await context.record_call(
        model_id="openai/gpt-4o-mini", role="generator", tokens_in=20, tokens_out=5
    )

    row = (
        await db.execute(select(UsageLedger).where(UsageLedger.run_id == run_id))
    ).scalar_one()
    assert row.status == "reserved"
    assert row.tokens_in == 20
    assert row.tokens_out == 5
    assert row.credits == 6.0


async def test_async_judge_usage_is_a_separate_settled_row(db: AsyncSession) -> None:
    user, run_id = await _run(db)
    await gate_and_reserve(
        db,
        user_id=user.id,
        run_id=run_id,
        mode="fast",
        settings={"quota_estimates": {"fast": 100}},
    )
    await db.commit()
    context = UsageContext(get_session_factory(), user.id, run_id, {})

    await context.record_call(
        model_id="anthropic/claude-haiku-4.5",
        role="async_judge",
        tokens_in=10,
        tokens_out=2,
    )

    rows = (
        await db.execute(select(UsageLedger).where(UsageLedger.run_id == run_id))
    ).scalars().all()
    assert len(rows) == 2
    assert {row.role for row in rows} == {"run", "async_judge"}
    assert context.snapshot().credits == 0.0


async def test_usage_context_is_task_local(db: AsyncSession) -> None:
    user, run_id = await _run(db)
    context = UsageContext(
        session_factory=get_session_factory(), user_id=user.id, run_id=run_id, model_roles={}
    )
    token = set_usage_context(context)
    try:
        assert set_usage_context is not None
        from quota.usage import get_usage_context

        assert get_usage_context() is context
    finally:
        from quota.usage import reset_usage_context

        reset_usage_context(token)
