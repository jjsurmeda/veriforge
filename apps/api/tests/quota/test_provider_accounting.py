from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message, Plan, Run, User
from db.session import get_session_factory
from providers.llm import complete, stream_completion
from quota.usage import UsageContext, reset_usage_context, set_usage_context


async def _run(db: AsyncSession) -> tuple[User, str]:
    plan = Plan(name=f"provider-{id(db)}", credits_5h=100, credits_month=100)
    user = User(email=f"provider-{id(db)}@test.dev", role="user", plan_id=plan.id)
    db.add(plan)
    await db.flush()
    user.plan_id = plan.id
    db.add(user)
    await db.flush()
    chat = Chat(user_id=user.id, title="provider")
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.flush()
    run = Run(message_id=message.id, status="running")
    db.add(run)
    await db.flush()
    await db.commit()
    return user, str(run.id)


async def test_complete_records_provider_usage(monkeypatch: Any, db: AsyncSession) -> None:
    user, run_id = await _run(db)
    context = UsageContext(
        get_session_factory(), user.id, UUID(run_id), {}, {"openai/gpt-4o-mini": "sk-test"}
    )
    seen: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake_acompletion)
    token = set_usage_context(context)
    try:
        await complete(
            litellm_model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "question"}],
            metadata={"role": "generator", "run_id": run_id, "user_id": str(user.id)},
        )
    finally:
        reset_usage_context(token)

    assert context.tokens_in == 100
    assert context.tokens_out == 20
    assert context.credits == 27.0
    assert seen["api_key"] == "sk-test"


async def test_stream_records_final_provider_usage(monkeypatch: Any, db: AsyncSession) -> None:
    user, run_id = await _run(db)
    context = UsageContext(get_session_factory(), user.id, UUID(run_id), {})

    class FakeResponse:
        async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
            yield {"choices": [{"delta": {"content": "hi"}}]}
            yield {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}

    async def fake_acompletion(**_: Any) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake_acompletion)
    token = set_usage_context(context)
    try:
        chunks = [
            chunk
            async for chunk in stream_completion(
                litellm_model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": "question"}],
                metadata={"role": "generator", "run_id": run_id, "user_id": str(user.id)},
            )
        ]
    finally:
        reset_usage_context(token)

    assert chunks == ["hi"]
    assert context.tokens_in == 5
    assert context.tokens_out == 3
    assert context.credits == 2.55
