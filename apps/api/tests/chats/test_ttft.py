"""TX-3: time to first token, per run.

`generate` measures only the generator's own loop. The number a person waiting
on a chat feels is everything before it — runtime resolution, ingress, rewrite,
retrieval, rerank, the sufficiency gate — so TTFT is measured from the moment
`execute_run` starts, not from when the generator does.

The end-to-end shape is borrowed wholesale from `test_auto_steps.py`: a real
Auto run over SSE with the DecisionEngine, the small model, the generator, the
reviewer and the guard all faked at their seams, so no test reaches a live
provider (testing.md) and the assertion is on the event stream, which is the
only place the requirement is observable.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Run, User
from decisions.output_guard import OutputGuardResult
from graph import auto as auto_module
from graph import runner as runner_module
from graph.review import ReviewResult
from retrieval.hybrid import ScoredChunk
from schemas.decisions import Answer, Question
from tests.retrieval.conftest import add_chunk, make_document, make_section, vec

QUESTION = "How long is the AW-2000 warranty?"
EMAIL = "ttft@test.dev"


class _AutoJev:
    """`sufficient` high and `risk` low, so the run streams and a first
    token exists at all."""

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        answers: dict[str, Answer] = {}
        for name in questions:
            if name == "intent":
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value="lookup", probability=0.95
                )
            elif name in {"source", "complexity"}:
                value = "both" if name == "source" else "single"
                answers[name] = Answer(engine="jev", latency_ms=1, value=value, probability=0.9)
            elif name == "risk":
                answers[name] = Answer(engine="jev", latency_ms=1, value="low", probability=0.95)
            elif name == "sufficient":
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.9, probability=0.9)
            else:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers


class _StubEngine:
    def __init__(self, **_: Any) -> None:
        self._jev = _AutoJev()

    def configure(self, _settings: Any) -> None:
        return None

    def set_event_emitter(self, _emitter: Any) -> None:
        return None

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        return await self._jev.decide(state=state, questions=questions)


class _PassThroughRerank:
    def __init__(self, *_args: object) -> None:
        pass

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        return [(i, 1.0 - i / 100) for i in range(min(top_n, len(documents)))]


async def _seed_one_chunk(db: AsyncSession, user: User) -> list[ScoredChunk]:
    from db.models import Collection

    collection = Collection(owner_id=user.id, name="docs", kind="library")
    db.add(collection)
    await db.flush()
    document = await make_document(db, collection, name="warranty_2025.md")
    section = await make_section(db, document)
    chunk = await add_chunk(
        db,
        document=document,
        section=section,
        ord=0,
        text_="The AW-2000 warranty is 24 months from the date of purchase.",
        embedding=vec(1),
    )
    await db.commit()
    return [
        ScoredChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.name,
            section_id=section.id,
            ord=0,
            page=None,
            text=chunk.text,
            heading_path=section.heading_path,
            source_type="document",
            vector_score=1.0,
            bm25_score=None,
            fused_score=1.0,
        )
    ]


async def _parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
    if data:
        yield event, json.loads("\n".join(data))


async def _run_auto_and_collect(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    question: str = QUESTION,
    tokens: tuple[str, ...] = ("24 ", "months."),
    delay_before_first_token_s: float = 0.0,
) -> tuple[list[tuple[str, dict[str, Any]]], UUID]:
    """Sign up, seed one chunk, run Auto, return the SSE transcript in order.

    `delay_before_first_token_s` sleeps inside the generator before yielding,
    which is the honest way to make TTFT and `generate` differ: with no delay
    a fast faked generator makes the two nearly the same number and a test
    asserting they differ proves nothing.
    """
    seen: dict[str, list[str]] = {"streamed": []}

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return "The warranty is 24 months."

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def _fake_tokens() -> AsyncIterator[str]:
        import asyncio

        seen["streamed"].append("called")
        for index, token in enumerate(tokens):
            if index == 0 and delay_before_first_token_s:
                await asyncio.sleep(delay_before_first_token_s)
            yield token

    async def fake_stream_grounded(**kwargs: Any) -> AsyncIterator[str]:
        async for token in _fake_tokens():
            yield token

    # The greeting fast path answers through a different generator (batch A,
    # 2026-09-28), so a "no tokens" case driven by a greeting needs this too —
    # otherwise the test would be exercising a live model.
    async def fake_stream_chitchat(**kwargs: Any) -> AsyncIterator[str]:
        async for token in _fake_tokens():
            yield token

    async def fake_review_answer(**kwargs: Any) -> Any:
        return ReviewResult()

    async def fake_suggestions(**kwargs: Any) -> list[str]:
        return []

    async def fake_guard_output(*args: Any, **kwargs: Any) -> Any:
        return OutputGuardResult()

    signup = await client.post(
        "/auth/signup", json={"email": EMAIL, "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one()
    chunks = await _seed_one_chunk(db, user)

    async def fake_search(*args: Any, **kwargs: Any) -> list[ScoredChunk]:
        return list(chunks)

    monkeypatch.setattr(runner_module, "DecisionEngine", _StubEngine)
    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)
    monkeypatch.setattr(auto_module, "stream_grounded_answer", fake_stream_grounded)
    monkeypatch.setattr(auto_module, "stream_chitchat_reply", fake_stream_chitchat)
    monkeypatch.setattr("graph.chat_title.complete", fake_complete)
    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard_output)

    chat = await client.post("/chats", json={}, headers=headers)
    chat_id = str(chat.json()["id"])
    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": question, "mode": "auto"}, headers=headers
    )
    assert started.status_code == 201, started.text
    run_id = UUID(started.json()["run_id"])

    transcript: list[tuple[str, dict[str, Any]]] = []
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        assert response.status_code == 200
        async for event_type, data in _parse_sse(response.aiter_lines()):
            transcript.append((event_type, data))
            if event_type in ("run.completed", "run.failed"):
                break
    assert seen["streamed"], "the generator must have run, or the timing proves nothing"
    return transcript, run_id


def _metrics_event(transcript: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    for event_type, data in transcript:
        if event_type == "metrics":
            return data
    raise AssertionError(f"no metrics event: {[t for t, _ in transcript]}")


class TestTimeToFirstToken:
    async def test_metrics_carries_a_first_token_time(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transcript, _ = await _run_auto_and_collect(client, db, monkeypatch)
        metrics = _metrics_event(transcript)
        assert isinstance(metrics["ttft_ms"], int)
        assert metrics["ttft_ms"] >= 0

    async def test_it_covers_the_work_before_the_generator_not_just_the_generator(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The distinction that matters: TTFT is the whole wait, `generate` is
        only the generator's loop. A slow generator inflates both; the pipeline
        before it inflates only TTFT. So the check is that TTFT is the larger
        number on a run whose generator was deliberately slow — and that the
        difference covers the non-generator stages."""
        transcript, _ = await _run_auto_and_collect(
            client, db, monkeypatch, delay_before_first_token_s=0.25
        )
        metrics = _metrics_event(transcript)
        generate = metrics["latency_ms"]["generate"]
        ttft = metrics["ttft_ms"]

        assert ttft > generate, (
            f"ttft {ttft} should exceed generate {generate}: the pipeline runs "
            "before the generator and neither number may exclude it"
        )
        # At least the deliberate 250 ms of generator delay, plus the stages.
        assert ttft >= 250, metrics

    async def test_it_is_persisted_for_a_reopened_run(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TX-3 is a Metrics-tab feature, and a Metrics tab on a past chat reads
        `runs.metrics`, not the stream. A value that never lands there is a value
        nobody can see after the run ends."""
        from db.session import get_session_factory

        _, run_id = await _run_auto_and_collect(client, db, monkeypatch)
        async with get_session_factory()() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            metrics: dict[str, Any] = run.metrics or {}
        assert isinstance(metrics["ttft_ms"], int)

    async def test_it_is_null_when_the_run_produced_no_answer_tokens(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A greeting answers without generating. Reporting 0 ms there would
        read as "instant", which is a different claim from "no first token"."""
        transcript, _ = await _run_auto_and_collect(
            client, db, monkeypatch, question="hello", tokens=()
        )
        metrics = _metrics_event(transcript)
        assert metrics["ttft_ms"] is None