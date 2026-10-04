"""Output caps, reasoning toggle, failover, concurrency cap and temperature
threading on every LLM call (known-issues KI-1, KI-2, KI-7, KI-17, KI-32).
LiteLLM is faked at its boundary."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from litellm.exceptions import BadRequestError, RateLimitError, ServiceUnavailableError

from config import get_settings
from providers.llm import complete, stream_completion

FREE = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
OK = {"choices": [{"message": {"content": "ok"}}]}


def _rate_limited(model: str) -> RateLimitError:
    return RateLimitError(message="429", llm_provider="openrouter", model=model)


def _overloaded(model: str) -> ServiceUnavailableError:
    return ServiceUnavailableError(
        message="provider_overloaded", llm_provider="openrouter", model=model
    )


def _chunks(*contents: str) -> list[dict[str, Any]]:
    return [{"choices": [{"delta": {"content": c}}]} for c in contents]


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


async def test_the_decision_fallback_role_gets_a_batch_sized_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KI-57: the fallback engine answers the whole batched decide call in one
    JSON object. Under the 512 default the largest batch (sufficiency plus the
    per-passage entity questions) truncated mid-JSON at the same offset on
    every degraded-jev run; the role therefore carries its own, larger cap.
    Mutation: drop the entry and the role falls back to the default."""
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    await complete(litellm_model=FREE, messages=[], metadata={"role": "decision_fallback"})

    settings = get_settings()
    assert seen[0]["max_tokens"] == settings.llm_max_tokens["decision_fallback"]
    assert seen[0]["max_tokens"] > settings.llm_default_max_tokens


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


async def test_reasoning_mandatory_400_retries_without_the_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """openrouter/free -> nemotron-3.5-lightning:free rejects
    reasoning-disabled calls with 400 "Reasoning is mandatory"; the call
    retries once without extra_body instead of failing the run."""

    def _mandatory(model: str) -> BadRequestError:
        return BadRequestError(
            message='{"error":{"message":"Reasoning is mandatory for this endpoint and '
            'cannot be disabled."}}',
            llm_provider="openrouter",
            model=model,
        )

    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        if "extra_body" in kwargs:
            raise _mandatory(kwargs["model"])
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await complete(litellm_model=FREE, messages=[], metadata={"role": "titler"}) == "ok"
    assert len(seen) == 2
    assert seen[0]["extra_body"] == {"reasoning": {"enabled": False}}
    assert "extra_body" not in seen[1]


async def test_unrelated_bad_request_still_raises_after_the_reasoning_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise BadRequestError(
            message="context length exceeded", llm_provider="openrouter", model=FREE
        )

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


async def _stream_out() -> list[str]:
    return [
        d
        async for d in stream_completion(
            litellm_model=FREE, messages=[], metadata={"role": "generator"}
        )
    ]


def _stream(*contents: str, dies: str | None = None) -> Any:
    """A litellm streaming response that yields these deltas, then (optionally)
    raises the provider error litellm surfaces when an upstream dies mid-flight."""

    class Stream:
        async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
            for content in contents:
                yield {"choices": [{"delta": {"content": content}}]}
            if dies is not None:
                raise _overloaded(dies)

    return Stream()


def _first_dies_rest_survives(monkeypatch: pytest.MonkeyPatch, opened: list[str]) -> None:
    async def fake(**kwargs: Any) -> Any:
        model = kwargs["model"]
        opened.append(model)
        if model == FREE:
            return _stream(*FIRST_DYING, dies=model)
        return _stream(*FIRST_SURVIVOR)

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)


FIRST_DYING = ("Hello", " there")
FIRST_SURVIVOR = ("Hello", " there", ",", " friend", ".")


async def test_mid_stream_death_restarts_on_the_fallback_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KI-17: a provider that dies after 2 chunks restarts the whole request on
    llm_fallback_model. The caller sees one clean answer and no error."""
    opened: list[str] = []
    _first_dies_rest_survives(monkeypatch, opened)
    assert await _stream_out() == list(FIRST_SURVIVOR)
    assert opened == [FREE, get_settings().llm_fallback_model]


async def test_a_death_inside_the_first_sentence_renders_nothing_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first sentence is withheld, so a death inside it costs the user
    nothing: the partial deltas never reach the caller."""
    opened: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        opened.append(kwargs["model"])
        if kwargs["model"] == FREE:
            return _stream("Hi", " ther", dies=kwargs["model"])
        return _stream("Hi", " there", ".")

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await _stream_out() == ["Hi", " there", "."]


async def test_a_death_after_the_first_sentence_still_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restarting mid-answer beats failing the run. The accepted hiccup is
    that the sentence already released is not retracted."""

    async def fake(**kwargs: Any) -> Any:
        if kwargs["model"] == FREE:
            return _stream("Hello there", ".", dies=kwargs["model"])
        return _stream("Hello again")

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await _stream_out() == ["Hello there", ".", "Hello again"]


async def test_an_unpunctuated_answer_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buffering also flushes at end of stream, so a reply with no sentence end
    still reaches the caller in full."""

    async def fake(**kwargs: Any) -> Any:
        return _stream("42", " apples")

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await _stream_out() == ["42", " apples"]


async def test_a_dead_stream_with_no_fallback_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "llm_fallback_model", "")

    async def fake(**kwargs: Any) -> Any:
        return _stream("hi", " there.", dies=kwargs["model"])

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    with pytest.raises(ServiceUnavailableError):
        await _stream_out()


async def test_a_dead_fallback_does_not_loop_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One hop only: if the fallback dies too, the error reaches the caller."""
    calls: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        calls.append(kwargs["model"])
        return _stream("hi", " there.", dies=kwargs["model"])

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    with pytest.raises(ServiceUnavailableError):
        await _stream_out()
    assert calls == [FREE, get_settings().llm_fallback_model]


# Temperature threading (KI-32). `None` must mean "send nothing" so every
# caller that predates the parameter keeps the provider default.


async def test_no_temperature_is_sent_unless_a_caller_pins_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    await complete(litellm_model=FREE, messages=[], metadata={"role": "generator"})

    assert "temperature" not in seen[0]


async def test_a_pinned_temperature_reaches_the_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    await complete(
        litellm_model=FREE, messages=[], metadata={"role": "claim_extractor"}, temperature=0
    )

    assert seen[0]["temperature"] == 0


async def test_a_pinned_temperature_survives_the_open_failover_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failover leg rebuilds the kwargs from scratch, so a pinned
    temperature has to be re-applied there or the retry silently runs at the
    provider default — the answer would vary again, which is the KI-32 symptom."""
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        if kwargs["model"] == FREE:
            raise _rate_limited(FREE)
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert (
        await complete(
            litellm_model=FREE, messages=[], metadata={"role": "claim_extractor"}, temperature=0
        )
        == "ok"
    )

    assert [call["model"] for call in seen] == [FREE, get_settings().llm_fallback_model]
    assert [call.get("temperature") for call in seen] == [0, 0]


async def test_a_pinned_temperature_survives_a_mid_stream_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KI-17's restart is a brand-new request to the fallback model, so it
    carries the same pinned temperature (KI-32)."""
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        seen.append(kwargs)
        if kwargs["model"] == FREE:
            return _stream(*FIRST_DYING, dies=kwargs["model"])
        return _stream(*FIRST_SURVIVOR)

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    out = [
        d
        async for d in stream_completion(
            litellm_model=FREE,
            messages=[],
            metadata={"role": "claim_extractor"},
            temperature=0,
        )
    ]

    assert out == list(FIRST_SURVIVOR)
    assert [call["model"] for call in seen] == [FREE, get_settings().llm_fallback_model]
    assert [call.get("temperature") for call in seen] == [0, 0]


async def test_the_reasoning_retry_keeps_the_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 400-retry drops extra_body and re-sends; the temperature has to
    survive that rewrite too, or the second attempt is a different call."""

    def _mandatory(model: str) -> BadRequestError:
        return BadRequestError(
            message='{"error":{"message":"Reasoning is mandatory for this endpoint and '
            'cannot be disabled."}}',
            llm_provider="openrouter",
            model=model,
        )

    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        if "extra_body" in kwargs:
            raise _mandatory(kwargs["model"])
        return OK

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    await complete(litellm_model=FREE, messages=[], metadata={"role": "titler"}, temperature=0.3)

    assert len(seen) == 2
    assert [call.get("temperature") for call in seen] == [0.3, 0.3]


async def test_a_stream_sends_no_temperature_unless_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return _stream("hi", " there.")

    monkeypatch.setattr("providers.llm.litellm.acompletion", fake)
    assert await _stream_out() == ["hi", " there."]
    assert "temperature" not in seen[0]
