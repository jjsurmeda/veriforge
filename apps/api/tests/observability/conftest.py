"""Fixtures for the signal tests.

Each returns a case that triggers exactly one signal, so a test can assert
both that the event fired and that it fired once.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Document, Message, Plan, Run, UsageLedger, User


async def _user_and_run(db: AsyncSession, *, credits: int, used: int) -> tuple[Any, Any]:
    plan = Plan(name=f"sig-{uuid4().hex[:8]}", credits_5h=credits, credits_month=credits)
    db.add(plan)
    await db.flush()
    user = User(email=f"sig-{uuid4().hex[:8]}@test.dev", role="user", plan_id=plan.id)
    db.add(user)
    await db.flush()
    chat = Chat(user_id=user.id, title="signals")
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.flush()
    run = Run(message_id=message.id, status="running")
    db.add(run)
    await db.flush()
    if used:
        # Credit already spent in the current window: a reservation larger
        # than what is left is refused with no further setup.
        db.add(
            UsageLedger(
                user_id=user.id,
                run_id=run.id,
                model="aggregate",
                role="run",
                tokens_in=0,
                tokens_out=0,
                credits=used,
                status="settled",
            )
        )
    await db.commit()
    return user, run.id


@pytest.fixture
async def quota_denied_case(db: AsyncSession) -> tuple[Any, Any, AsyncSession]:
    """A user with less credit left than a run's estimate."""
    user, run_id = await _user_and_run(db, credits=100, used=90)
    return user.id, run_id, db


@pytest.fixture
async def quota_allowed_case(db: AsyncSession) -> tuple[Any, Any, AsyncSession]:
    """A user with credit to spare — must emit nothing."""
    user, run_id = await _user_and_run(db, credits=10_000_000, used=0)
    return user.id, run_id, db


@pytest.fixture
async def failed_document(db: AsyncSession) -> Any:
    """A queued document, so `_mark_failed` has a row to fail.

    A document belongs to a collection (TRD §9.1), not directly to a user,
    so the fixture creates the collection first.
    """
    user, _ = await _user_and_run(db, credits=100, used=0)
    from db.models import Collection

    collection = Collection(
        owner_id=user.id,
        name=f"sig-{uuid4().hex[:8]}",
        visibility="private",
        kind="library",
    )
    db.add(collection)
    await db.flush()
    document = Document(
        collection_id=collection.id,
        name="broken.pdf",
        mime="application/pdf",
        sha256=uuid4().hex * 2,
        s3_key=f"sig/{uuid4().hex}.pdf",
        status="queued",
    )
    db.add(document)
    await db.commit()
    return document.id


def _process_breaker() -> Any:
    """The process-wide breaker, cleared so the test starts from closed.

    Driven rather than patched: `get_breaker` is `@cache`d, so clearing the
    cache and calling the recorded failures against the real object tests
    the same code path production runs, with no module reloading to undo
    afterwards.
    """
    from decisions.breaker import get_breaker

    get_breaker.cache_clear()
    return get_breaker()


@pytest.fixture
async def running_run_with_heartbeat(db: AsyncSession) -> Any:
    """A running run whose heartbeat is a known age, for the healthz field.

    Created rather than looked up: a test that skips when the fixture
    database happens to be empty is a test that quietly stops asserting the
    field an alarm is built on.
    """
    from datetime import UTC, datetime, timedelta

    _user, run_id = await _user_and_run(db, credits=100, used=0)
    run = await db.get(Run, run_id)
    assert run is not None
    run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=90)
    await db.commit()
    return run_id


@pytest.fixture
def breaker_closed() -> Any:
    return _process_breaker()


@pytest.fixture
def breaker_open() -> Any:
    breaker = _process_breaker()
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()
    assert breaker.state.value == "open"
    return breaker