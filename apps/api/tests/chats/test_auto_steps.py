"""CH-5 (progress, live): an Auto run publishes its steps as it runs.

`prepare_auto_run` already TIMED every step through `_step`, but the runner
never handed it a publisher, so nothing reached the bus: the trace stayed
empty for the whole prepare phase and filled in only once the run was already
over. Deep mode has always passed `publish=`; Auto did not. This drives a
real Auto run over SSE and asserts on the event order, which is the only
place the requirement ("emits step events before the first delta") is
observable.

No live provider: DecisionEngine, the small model and the generator are all
faked at their seams.
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
EMAIL = "autosteps@test.dev"


class _AutoJev:
    """Answers every question the Auto path asks. `risk` low and
    `sufficient` high, so `plan_delivery` chooses "stream" and deltas are
    published as they are produced rather than held for review."""

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
            elif name == "lexical_weight":
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.5, probability=0.5)
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


async def _auth(client: AsyncClient) -> dict[str, str]:
    signup = await client.post("/auth/signup", json={"email": EMAIL, "password": "password123"})
    return {"Authorization": f"Bearer {signup.json()['access_token']}"}


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


async def _seed_one_chunk(db: AsyncSession, user: User) -> list[ScoredChunk]:
    """One real chunk, so small-to-big expansion and the sufficiency gate
    have something to work with."""
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


async def _run_auto_and_collect(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, dict[str, Any]]], UUID]:
    """Sign up, seed one chunk, run in Auto mode, and return the SSE
    transcript in order."""
    seen: dict[str, list[str]] = {"streamed": []}

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return "The warranty is 24 months."

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def fake_stream_grounded(**kwargs: Any) -> AsyncIterator[str]:
        seen["streamed"].append("called")
        for token in ("24 ", "months."):
            yield token

    async def fake_review_answer(**kwargs: Any) -> Any:
        return ReviewResult()

    async def fake_suggestions(**kwargs: Any) -> list[str]:
        return []

    async def fake_guard_output(*args: Any, **kwargs: Any) -> Any:
        return OutputGuardResult()

    headers = await _auth(client)
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
    monkeypatch.setattr("graph.chat_title.complete", fake_complete)
    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard_output)

    chat = await client.post("/chats", json={}, headers=headers)
    chat_id = str(chat.json()["id"])
    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": QUESTION, "mode": "auto"}, headers=headers
    )
    assert started.status_code == 201, started.text
    run_id = UUID(started.json()["run_id"])

    transcript: list[tuple[str, dict[str, Any]]] = []
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        assert response.status_code == 200
        async for event_type, data in _parse_sse(response.aiter_lines()):
            transcript.append((event_type, data))
            if event_type == "run.completed":
                break
    assert seen["streamed"], "the generator must have run, or the ordering proves nothing"
    return transcript, run_id


async def test_auto_publishes_a_step_per_query_variant_before_the_first_delta(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CH-5 stated as the requirement is: the user sees the work happening.
    At least one `step.started` per query variant, all of them before the
    first `answer.delta`."""
    transcript, _ = await _run_auto_and_collect(client, db, monkeypatch)
    types = [event_type for event_type, _ in transcript]

    assert "answer.delta" in types, types
    first_delta = types.index("answer.delta")
    step_started = [i for i, (t, _) in enumerate(transcript) if t == "step.started"]
    assert step_started, f"no step.started events at all: {types}"
    assert min(step_started) < first_delta, (
        f"steps must precede the first delta; step.started at {step_started}, "
        f"first answer.delta at {first_delta}"
    )

    labels = [transcript[i][1]["label"] for i in step_started]
    variant_labels = [label for label in labels if label.startswith("retrieve: ")]
    assert variant_labels, f"no per-variant retrieval sub-step: {labels}"
    # one per variant, each naming the query it ran, and each completed too
    assert len(variant_labels) == len(set(variant_labels)), variant_labels
    for label in variant_labels:
        assert label.removeprefix("retrieve: ").strip(), label
    completed = [
        transcript[i][1]["label"] for i, (t, _) in enumerate(transcript) if t == "step.completed"
    ]
    for label in variant_labels:
        assert label in completed, f"{label} started but never completed"


async def test_per_variant_substeps_do_not_pollute_the_run_latency_metrics(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sub-step labels carry query text. `latency_ms` is published as the
    run's node metrics, so a per-variant entry there would put a query string
    in a metric key and add one key per variant per run. The outer `retrieve`
    step still carries the total."""
    from db.session import get_session_factory

    transcript, run_id = await _run_auto_and_collect(client, db, monkeypatch)
    labels = [data["label"] for event_type, data in transcript if event_type == "step.started"]
    assert any(label.startswith("retrieve: ") for label in labels), labels

    async with get_session_factory()() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        metrics: dict[str, Any] = run.metrics or {}
    latency: dict[str, Any] = metrics.get("latency_ms", {})
    assert "retrieve" in latency, latency
    assert not any(key.startswith("retrieve:") for key in latency), latency
