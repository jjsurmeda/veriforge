"""A Deep-mode stream error must end the iteration, not hang the run (S5).

`DeepRun.stream_answer_with_thinking` runs `stream_grounded_answer` in a
producer task and reads an `asyncio.Queue` for the interleaved thinking /
content tokens. The `None` end sentinel was only queued after the producer's
`async for` finished normally, so a provider or stream failure mid-answer
left the consumer blocked on `queue.get()` forever: the client's SSE stream
stayed open and the run stayed `running` until the stale-heartbeat sweeper
intervened, masking the real error.

`_drain_within` is the decisive check: it awaits the drain as a task and does
NOT cancel it on timeout, so a consumer that never receives the sentinel is
still pending when the deadline passes and the test fails with "hung". A
cancelling wrapper would hide the bug, because the generator's own `finally`
then awaits the already-failed producer and raises the right exception from
the cancellation path.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast
from uuid import uuid4

import pytest

import graph.deep as deep_module
from graph.deep import DeepRun
from graph.ingress import IngressOutcome
from retrieval.filters import ClientFilters
from schemas.events import Plan

DEADLINE_SECONDS = 2.0


def _deep_run() -> DeepRun:
    run_id = uuid4()
    return DeepRun(
        params=deep_module.DeepRunInput(
            run_id=run_id,
            message_id=uuid4(),
            chat_id=uuid4(),
            user_id=uuid4(),
            question="q",
            litellm_model="openrouter/anthropic/claude-haiku-4.5",
            small_model="openrouter/anthropic/claude-haiku-4.5",
            context_window=128_000,
            source="upload",
            client_filters=ClientFilters(),
            collection_ids=[],
        ),
        history=[],
        contexts=[],
        kept_chunks=[],
        dropped_chunks=[],
        rewritten="q",
        plan_event=Plan(run_id=str(run_id), sub_questions=[]),
        retrieval_events=[],
        decision_events=[],
        abstain_event=None,
        latency_ms={},
        context_used=0,
        ingress=IngressOutcome(
            intent="lookup",
            source="both",
            complexity="multi",
            risk="low",
            lexical_weight=0.5,
            guard_injection="pass",
            guard_jailbreak="pass",
            guard_pii="pass",
            off_topic="pass",
        ),
        credits_used=0,
    )


def _fake_stream(tokens: list[str], *, fail_before: str | None) -> Any:
    async def stream_grounded_answer(**_kwargs: Any) -> AsyncIterator[str]:
        for token in tokens:
            if token == fail_before:
                raise RuntimeError("provider stream died mid-answer")
            yield token

    return stream_grounded_answer


async def _drain_within(run: DeepRun, seconds: float = DEADLINE_SECONDS) -> list[tuple[str, str]]:
    """Drain the stream; fail loudly if the consumer never gets the sentinel."""
    seen: list[tuple[str, str]] = []

    async def consume() -> None:
        async for item in run.stream_answer_with_thinking():
            seen.append(item)

    task = asyncio.create_task(consume())
    done, _pending = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        raise AssertionError(
            f"stream_answer_with_thinking hung for {seconds}s: no end sentinel after a "
            "producer failure, so the run would stay streaming forever"
        )
    await task  # re-raises whatever ended the producer
    return seen


async def test_mid_stream_error_ends_the_iteration_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deep_module,
        "stream_grounded_answer",
        _fake_stream(["Hello ", "there", "friend"], fail_before="there"),
    )

    with pytest.raises(RuntimeError, match="died mid-answer"):
        await _drain_within(_deep_run())


async def test_mid_stream_error_still_yields_the_tokens_before_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run ends, but the client keeps the part of the answer it did get."""
    monkeypatch.setattr(
        deep_module,
        "stream_grounded_answer",
        _fake_stream(["Hello ", "there", "friend"], fail_before="there"),
    )
    run = _deep_run()
    seen: list[tuple[str, str]] = []

    async def consume() -> None:
        async for item in run.stream_answer_with_thinking():
            seen.append(item)

    task = asyncio.create_task(consume())
    done, _pending = await asyncio.wait({task}, timeout=DEADLINE_SECONDS)
    assert done, "the stream hung after a producer failure"
    with pytest.raises(RuntimeError, match="died mid-answer"):
        await task
    assert seen == [("content", "Hello ")]


async def test_a_normal_stream_still_ends_on_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deep_module, "stream_grounded_answer", _fake_stream(["a", "b"], fail_before=None)
    )
    assert await _drain_within(_deep_run()) == [("content", "a"), ("content", "b")]


async def test_a_consumer_that_stops_early_does_not_leak_the_producer_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deep_module, "stream_grounded_answer", _fake_stream(["a", "b", "c"], fail_before=None)
    )
    run = _deep_run()
    stream = run.stream_answer_with_thinking()
    assert await stream.__anext__() == ("content", "a")
    before = len(asyncio.all_tasks())
    await cast(AsyncGenerator[tuple[str, str]], stream).aclose()
    assert len(asyncio.all_tasks()) <= before, "the producer task outlived its consumer"
