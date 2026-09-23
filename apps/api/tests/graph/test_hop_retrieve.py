"""Hop retrieve node tests (TRD §7 Deep row): retrieval against the real
test Postgres, DecisionEngine mocked — no live model."""

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from decisions.engine import DecisionEngine
from graph import hop_retrieve as hop_retrieve_module
from graph.hop_retrieve import HopNote, ready_sub_questions, run_hop, run_hop_batch
from retrieval.filters import ClientFilters
from schemas.decisions import Answer, Question
from schemas.events import Retrieval, SubQuestion
from tests.retrieval.conftest import add_chunk, make_collection, make_document, make_section, vec


class _AllowAllJev:
    """sanitizer's chunk_injection Noul always answers 'no' (low probability)."""

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        return {
            name: Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            for name in questions
        }


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    from tests.retrieval.conftest import make_user

    return await make_user(db, "hop-a@test.dev")


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed_batch(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed_batch)


async def test_run_hop_returns_kept_chunks_and_note(db: AsyncSession, user_a: User) -> None:
    collection = await make_collection(db, user_a, "docs")
    document = await make_document(db, collection)
    section = await make_section(db, document)
    await add_chunk(
        db, document=document, section=section, ord=0,
        text_="the AW-2000 blade warranty lasts 12 months", embedding=vec(1, bump=1),
    )
    await db.commit()

    engine = DecisionEngine(jev=_AllowAllJev(), mode="jev_only")
    sub_question = SubQuestion(id="q1", question="blade warranty length", depends_on=[])
    note = await run_hop(
        db,
        engine=engine,
        run_id=user_a.id,
        hop_index=1,
        sub_question=sub_question,
        user_id=user_a.id,
        collection_ids=[collection.id],
        chat_id=user_a.id,
        client_filters=ClientFilters(),
        lexical_weight=0.5,
    )
    assert note.sub_question.id == "q1"
    assert note.kept_chunks
    assert "warranty" in note.note
    assert note.retrieval_event.hop == 1
    assert not note.dropped_chunks


def test_ready_sub_questions_respects_dependencies() -> None:
    plan = [
        SubQuestion(id="q1", question="a", depends_on=[]),
        SubQuestion(id="q2", question="b", depends_on=["q1"]),
        SubQuestion(id="q3", question="c", depends_on=[]),
    ]
    batch1 = ready_sub_questions(plan, answered_ids=set())
    assert {sq.id for sq in batch1} == {"q1", "q3"}

    batch2 = ready_sub_questions(plan, answered_ids={"q1", "q3"})
    assert {sq.id for sq in batch2} == {"q2"}

    batch3 = ready_sub_questions(plan, answered_ids={"q1", "q2", "q3"})
    assert batch3 == []


async def test_run_hop_batch_executes_concurrently_not_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the TRD's explicit 'parallel' requirement — a
    silent regression to sequential hops would blow the 30s p50 target."""
    delay = 0.05
    call_order: list[str] = []

    async def fake_run_hop(session: object, **kwargs: Any) -> HopNote:
        call_order.append(kwargs["sub_question"].id)
        await asyncio.sleep(delay)
        return HopNote(
            sub_question=kwargs["sub_question"],
            note="note",
            kept_chunks=[],
            dropped_chunks=[],
            retrieval_event=Retrieval(
                run_id="r", hop=kwargs["hop_index"], query="q", chunks=[]
            ),
            decision_answers={},
        )

    monkeypatch.setattr(hop_retrieve_module, "run_hop", fake_run_hop)

    sub_questions = [
        SubQuestion(id="q1", question="a", depends_on=[]),
        SubQuestion(id="q2", question="b", depends_on=[]),
        SubQuestion(id="q3", question="c", depends_on=[]),
    ]
    started = time.monotonic()
    notes = await run_hop_batch(
        sub_questions,
        session=None,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
        run_id="r1",  # type: ignore[arg-type]
        hop_index=1,
        user_id="u1",  # type: ignore[arg-type]
        collection_ids=[],
        chat_id="c1",  # type: ignore[arg-type]
        client_filters=ClientFilters(),
        lexical_weight=0.5,
    )
    elapsed = time.monotonic() - started
    assert len(notes) == 3
    # 3 sequential calls would take >= 3*delay; concurrent execution stays
    # near one delay's worth of wall-clock time.
    assert elapsed < delay * 2
