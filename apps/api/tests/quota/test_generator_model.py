"""KI-3: the composer's model pick has to reach the generator.

`resolve_model` used to return `model_roles.get(role, requested)` for every
role, so the admin's `generator` mapping silently overrode whatever the
user picked. The generator now honours the request; the role mapping is
only the default, applied upstream when the chat has no model_id.
"""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message, Plan, Run, User
from db.session import get_session_factory
from quota.service import calculate_credits
from quota.usage import UsageContext

ROLES = {
    "generator": "openrouter/openai/gpt-4o-mini",
    "small": "openrouter/anthropic/claude-haiku-4.5",
}


async def _user_and_run(db: AsyncSession) -> tuple[User, UUID]:
    plan = Plan(name=f"ki3-{id(db)}", credits_5h=100, credits_month=100)
    db.add(plan)
    await db.flush()
    user = User(email=f"ki3-{id(db)}@test.dev", role="user", plan_id=plan.id)
    db.add(user)
    await db.flush()
    chat = Chat(user_id=user.id, title="ki3")
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


def _context(db: AsyncSession, user: User, run_id: UUID) -> UsageContext:
    return UsageContext(
        session_factory=get_session_factory(),
        user_id=user.id,
        run_id=run_id,
        model_roles=ROLES,
    )


async def test_generator_honours_the_requested_model(db: AsyncSession) -> None:
    user, run_id = await _user_and_run(db)
    context = _context(db, user, run_id)

    resolved = await context.resolve_model("openrouter/anthropic/claude-haiku-4.5", "generator")

    assert resolved == "openrouter/anthropic/claude-haiku-4.5"


async def test_generator_credits_are_recorded_against_the_model_that_ran(
    db: AsyncSession,
) -> None:
    user, run_id = await _user_and_run(db)
    context = _context(db, user, run_id)

    await context.record_call(
        model_id="openrouter/anthropic/claude-haiku-4.5",
        role="generator",
        tokens_in=1000,
        tokens_out=100,
    )

    # Asserting on the price rather than a magic number: if the ledger had
    # priced gpt-4o-mini from the role mapping this would be ~6x smaller.
    assert context.snapshot().credits == calculate_credits(
        price_in=1.0,
        price_out=5.0,
        reference_price=1.0,
        tokens_in=1000,
        tokens_out=100,
    )


async def test_other_roles_stay_admin_controlled(db: AsyncSession) -> None:
    user, run_id = await _user_and_run(db)
    context = _context(db, user, run_id)

    assert await context.resolve_model("openrouter/ignored", "small") == (
        "openrouter/anthropic/claude-haiku-4.5"
    )
    assert await context.resolve_model("openrouter/ignored", "planner") == "openrouter/ignored"


async def test_a_new_chat_with_no_pick_defaults_to_the_generator_role(
    client: AsyncClient,
) -> None:
    signup = await client.post(
        "/auth/signup", json={"email": "ki3@test.dev", "password": "password123"}
    )
    assert signup.status_code == 201, signup.text
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    created = await client.post("/chats", json={}, headers=headers)

    assert created.status_code == 201, created.text
    assert created.json()["model_id"] == "openai/gpt-4o-mini"
