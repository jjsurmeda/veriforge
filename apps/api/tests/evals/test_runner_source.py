"""Eval runs are documents-only (TRD §15, D2 item 2a).

`source="auto"` routed ingress to Tavily, so fast20 measured the web, not
the product: 16 of 20 items cited `source_type='web'` chunks and the
should-abstain items were answered from web pages, which made the
abstention number an artefact. The UI never sends "auto"
(`ChatComposer.tsx` sends "upload"/"both"). Pin `source="upload"` on both
the auto and the deep branch.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import EvalDataset, EvalItem, Plan, User
from evals import runner
from evals.attribution import Attribution
from evals.loader import EVAL_USER_EMAIL

pytestmark = pytest.mark.asyncio


class _FakeRun:
    """The surface _run_item touches, for either mode."""

    def __init__(self) -> None:
        self.latency_ms: dict[str, int] = {}
        self.contexts: list[Any] = []
        self.abstain_event = None
        self.rewritten = "q"
        self.history: list[tuple[str, str]] = []

    async def stream_answer(self) -> AsyncIterator[str]:
        yield "answer"

    async def stream_answer_with_thinking(self) -> AsyncIterator[tuple[str, str]]:
        yield ("content", "answer")


async def _seed_eval_user(db: AsyncSession) -> User:
    from db.models import EvalRun

    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    user = User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active")
    db.add(user)
    dataset = EvalDataset(name="seed")
    db.add(dataset)
    await db.flush()
    item = EvalItem(
        dataset_id=dataset.id,
        category="single_document_lookup",
        question="q?",
        reference_answer="",
        should_abstain=False,
    )
    db.add(item)
    db.add(EvalRun(dataset_id=dataset.id, mode="auto", is_baseline=False))
    await db.commit()
    return user


async def _run_one_item(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    mode: str,
) -> str:
    """Drive _run_item with the pipeline stubbed; return the captured source."""
    from evals.loader import EVAL_USER_EMAIL as EMAIL

    user = (
        await db.execute(select(User).where(User.email == EMAIL))
    ).scalar_one()
    dataset = (
        await db.execute(select(EvalDataset).where(EvalDataset.name == "seed"))
    ).scalar_one()
    item = (
        await db.execute(select(EvalItem).where(EvalItem.dataset_id == dataset.id))
    ).scalar_one()

    state = tmp_path / "loaded.json"
    state.write_text(json.dumps({"corpus_collection_id": "01a0ccca-0000-0000-0000-000000000000"}))
    monkeypatch.setattr(runner, "STATE_FILE", state)

    captured: dict[str, str] = {}

    async def fake_prepare_auto(
        factory: async_sessionmaker[AsyncSession], params: Any, engine: Any, **kwargs: Any
    ) -> _FakeRun:
        captured["source"] = params.source
        return _FakeRun()

    async def fake_prepare_deep(
        factory: async_sessionmaker[AsyncSession], params: Any, engine: Any, **kwargs: Any
    ) -> _FakeRun:
        captured["source"] = params.source
        return _FakeRun()

    async def fake_finalize(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_resolve_scope(*args: Any, **kwargs: Any) -> list[UUID]:
        return []

    async def fake_attribute(total_ms: float, generation_ids: list[str]) -> Attribution:
        return Attribution(total_ms=total_ms, provider_ms=0, attributed=0, unattributed=0)

    class _Review:
        scores = None
        # `_run_item` reads these to build `review_detail` (item 3); this test
        # is about `source`, so an empty review is enough.
        def __init__(self) -> None:
            self.claims: list[object] = []
            self.revised_text = None

    async def fake_review(**kwargs: Any) -> _Review:
        return _Review()

    async def fake_judge(**kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runner, "prepare_auto_run", fake_prepare_auto)
    monkeypatch.setattr(runner, "prepare_deep_run", fake_prepare_deep)
    monkeypatch.setattr(runner, "finalize_auto_run", fake_finalize)
    monkeypatch.setattr(runner, "finalize_deep_run", fake_finalize)
    monkeypatch.setattr(runner, "resolve_scope", fake_resolve_scope)
    monkeypatch.setattr(runner, "attribute", fake_attribute)
    monkeypatch.setattr(runner, "review_answer", fake_review)
    monkeypatch.setattr(runner, "judge_answer", fake_judge)

    from db.models import EvalRun
    from db.session import get_session_factory

    eval_run_id = (
        await db.execute(select(EvalRun.id))
    ).scalar_one()
    await runner._run_item(
        get_session_factory(), user=user, eval_run_id=eval_run_id, item=item, mode=mode
    )
    return captured["source"]


async def test_auto_eval_runs_are_documents_only(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    await _seed_eval_user(db)
    assert await _run_one_item(db, monkeypatch, tmp_path, mode="auto") == "upload"


async def test_deep_eval_runs_are_documents_only(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    await _seed_eval_user(db)
    assert await _run_one_item(db, monkeypatch, tmp_path, mode="deep") == "upload"
