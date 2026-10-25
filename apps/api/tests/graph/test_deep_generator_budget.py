"""Deep's generator has its own, larger token budget (KI-97), and the
provider's finish_reason for it is kept. Auto's budget does not change."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

import graph.deep as deep_module
from config import get_settings
from graph import generate as generate_module
from graph.generate import stream_grounded_answer
from providers.llm import stream_completion
from tests.graph.test_deep_stream_error import _deep_run

FREE = "openrouter/test/free"


async def test_deep_passes_its_own_budget_and_records_a_length_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake(**kwargs: Any) -> AsyncIterator[str]:
        seen.update(kwargs)
        kwargs["on_finish"]("length")
        yield "partial"

    monkeypatch.setattr(deep_module, "stream_grounded_answer", fake)
    run = _deep_run()
    async for _ in run.stream_answer_with_thinking():
        pass
    assert seen["max_tokens"] == get_settings().deep_generator_max_tokens == 8192
    assert run.generation_finish_reason == "length"


async def test_auto_generation_sends_no_extra_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def spy(**kwargs: Any) -> AsyncIterator[str]:
        seen.update(kwargs)
        yield "tok"

    monkeypatch.setattr(generate_module, "stream_completion", spy)
    async for _ in stream_grounded_answer(
        litellm_model=FREE, question="q", contexts=[], history=[], metadata={"run_id": "r"}
    ):
        pass
    assert seen["max_tokens"] is None


async def test_stream_raises_the_cap_and_reports_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    class Stream:
        async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
            yield {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
            yield {"choices": [{"delta": {}, "finish_reason": "length"}]}

    async def fake(**kwargs: Any) -> Stream:
        sent.update(kwargs)
        return Stream()

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    reasons: list[str] = []
    out = [
        d
        async for d in stream_completion(
            litellm_model=FREE,
            messages=[],
            metadata={"role": "generator"},
            max_tokens=8192,
            on_finish=reasons.append,
        )
    ]
    assert out == ["hi"]
    assert sent["max_tokens"] == 8192
    assert reasons == ["length"]
