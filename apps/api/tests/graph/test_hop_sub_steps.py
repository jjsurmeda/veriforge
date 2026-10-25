"""KI-93: Deep's hop shows retrieve, rerank and sanitize as sub-steps (no DB)."""

from typing import Any
from uuid import uuid4

import pytest

from graph import hop_retrieve as hop
from graph.timing import make_sub_step_timer
from retrieval.filters import ClientFilters
from schemas.events import RunStreamEvent, StepCompleted, StepStarted, SubQuestion


async def _fake(*_a: Any, **_k: Any) -> list[Any]:
    return []


async def _fake_sanitize(*_a: Any, **_k: Any) -> tuple[list[Any], list[Any], dict[str, Any]]:
    return [], [], {}


@pytest.fixture(autouse=True)
def _stub_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    async def embed(*_a: Any, **_k: Any) -> list[float]:
        return [0.0]

    monkeypatch.setattr(hop, "get_query_embedding", embed)
    monkeypatch.setattr(hop, "hybrid_search", _fake)
    monkeypatch.setattr(hop, "apply_rerank", _fake)
    monkeypatch.setattr(hop, "get_reranker", lambda *_a, **_k: None)
    monkeypatch.setattr(hop, "sanitize_chunks", _fake_sanitize)


async def _run(sub_step: Any, run_id: Any) -> None:
    await hop.run_hop(
        None,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
        run_id=run_id,
        hop_index=1,
        sub_question=SubQuestion(id="q1", question="warranty?", depends_on=[]),
        user_id=uuid4(),
        collection_ids=[],
        chat_id=uuid4(),
        client_filters=ClientFilters(),
        lexical_weight=0.5,
        sub_step=sub_step,
    )


async def test_hop_publishes_started_and_completed_for_each_stage() -> None:
    run_id = uuid4()
    events: list[RunStreamEvent] = []

    async def publish(_run: Any, event: RunStreamEvent) -> None:
        events.append(event)

    await _run(make_sub_step_timer(publish, node="deep", run_id=run_id), run_id)

    seen = [(type(e), e.label) for e in events if isinstance(e, StepStarted | StepCompleted)]
    expected = []
    for label in ("retrieve: q1", "rerank: q1", "sanitize: q1"):
        expected += [(StepStarted, label), (StepCompleted, label)]
    assert seen == expected


async def test_hop_without_a_sub_step_publisher_publishes_nothing() -> None:
    await _run(None, uuid4())  # no raise, no events: the pre-KI-93 behaviour
