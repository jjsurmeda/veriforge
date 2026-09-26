"""Output caps, reasoning toggle, failover and concurrency cap on every LLM
call (known-issues KI-1, KI-2, KI-7). LiteLLM is faked at its boundary."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from litellm.exceptions import BadRequestError, RateLimitError

from config import get_settings
from providers.llm import complete, stream_completion

FREE = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
OK = {"choices": [{"message": {"content": "ok"}}]}


def _rate_limited(model: str) -> RateLimitError:
    return RateLimitError(message="429", llm_provider="openrouter", model=model)


async def test_every_call_is_capped_per_role(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    for role in ("generator", "titler", "unknown-role"):
        await complete(litellm_model=FREE, messages=[], metadata={"role": role})

    settings = get_settings()
    assert seen[0]["max_tokens"] == settings.llm_max_tokens["generator"]
    assert seen[1]["max_tokens"] == settings.llm_default_max_tokens
    assert seen[2]["max_tokens"] == settings.llm_default_max_tokens


async def test_reasoning_is_off_except_for_reasoning_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, dict[str, Any]] = {}

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen[kwargs["metadata"]["role"]] = kwargs
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    await complete(litellm_model=FREE, messages=[], metadata={"role": "generator"})
    await complete(litellm_model=FREE, messages=[], metadata={"role": "planner"})
    await complete(
        litellm_model="anthropic/claude-haiku-4.5", messages=[], metadata={"role": "titler"}
    )

    assert seen["generator"]["extra_body"] == {"reasoning": {"enabled": False}}
    assert "extra_body" not in seen["planner"]
    assert "extra_body" not in seen["titler"]  # only OpenRouter takes the flag


async def test_rate_limit_fails_over_to_the_fallback_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        models.append(kwargs["model"])
        if kwargs["model"] == FREE:
            raise _rate_limited(FREE)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await complete(litellm_model=FREE, messages=[], metadata={"role": "titler"}) == "ok"
    assert models == [FREE, get_settings().llm_fallback_model]


async def test_non_transient_errors_do_not_fail_over(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise BadRequestError(message="bad", llm_provider="openrouter", model=FREE)

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    with pytest.raises(BadRequestError):
        await complete(litellm_model=FREE, messages=[], metadata={"role": "titler"})
    assert calls == 1


async def test_stream_fails_over_before_the_first_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
            yield {"choices": [{"delta": {"content": "hi"}}]}

    async def fake(**kwargs: Any) -> Stream:
        if kwargs["model"] == FREE:
            raise _rate_limited(FREE)
        return Stream()

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    out = [
        d
        async for d in stream_completion(
            litellm_model=FREE, messages=[], metadata={"role": "generator"}
        )
    ]
    assert out == ["hi"]


async def test_concurrency_is_capped_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_max_concurrency", 2)
    in_flight = peak = 0

    async def fake(**kwargs: Any) -> dict[str, Any]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    model = "openrouter/test/cap-model:free"  # fresh key: no semaphore from other tests
    await asyncio.gather(
        *(complete(litellm_model=model, messages=[], metadata={"role": "titler"}) for _ in range(5))
    )
    assert peak == 2


async def test_a_thinking_stream_keeps_reasoning_on(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Stream:
        async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
            yield {"choices": [{"delta": {"content": "hi"}}]}

    async def fake(**kwargs: Any) -> Stream:
        seen.update(kwargs)
        return Stream()

    async def on_reasoning(_: str) -> None:
        return None

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    out = [
        d
        async for d in stream_completion(
            litellm_model=FREE,
            messages=[],
            metadata={"role": "generator"},
            on_reasoning=on_reasoning,
        )
    ]
    assert out == ["hi"]
    assert "extra_body" not in seen
