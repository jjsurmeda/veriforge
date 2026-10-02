from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from graph import generate as generate_module
from graph.generate import stream_grounded_answer
from retrieval.expand import ExpandedContext
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings


@pytest.fixture
def contexts() -> list[ExpandedContext]:
    return []


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace stream_completion with a spy that records what it is handed."""
    seen: list[dict[str, Any]] = []

    async def spy(**kwargs: Any) -> AsyncIterator[str]:
        seen.append(kwargs)
        for token in ("tok",):
            yield token

    monkeypatch.setattr(generate_module, "stream_completion", spy)
    return seen


@contextmanager
def _with_runtime(data: dict[str, Any]) -> Iterator[None]:
    """Install a runtime settings context for the duration of a block, and
    undo it after — the contextvar is per-run, so a test that leaves one set
    would leak into the next."""
    token = set_runtime_settings(RuntimeSettings.from_data(1, data))
    try:
        yield
    finally:
        reset_runtime_settings(token)


async def _drain(contexts: list[ExpandedContext]) -> list[str]:
    return [
        token
        async for token in stream_grounded_answer(
            litellm_model="openrouter/test/generator",
            question="what does it say",
            contexts=contexts,
            history=[],
            metadata={"run_id": "r"},
        )
    ]


async def test_generator_sends_no_temperature_when_the_setting_is_unset(
    captured: list[dict[str, Any]], contexts: list[ExpandedContext]
) -> None:
    """The default is the point: unset means "send nothing", so the request is
    identical to the one made before this setting existed."""
    with _with_runtime({}):
        assert await _drain(contexts) == ["tok"]
    assert captured[0]["temperature"] is None


async def test_generator_forwards_a_configured_runtime_temperature(
    captured: list[dict[str, Any]], contexts: list[ExpandedContext]
) -> None:
    with _with_runtime({"generation": {"temperature": 0.2}}):
        assert await _drain(contexts) == ["tok"]
    assert captured[0]["temperature"] == 0.2


async def test_an_explicit_null_sends_nothing_rather_than_zero(
    captured: list[dict[str, Any]], contexts: list[ExpandedContext]
) -> None:
    """`null` and `0.0` are different requests. `null` means "use the provider
    default"; `0.0` pins greedy decoding. Collapsing them would silently change
    generation for anyone who set the knob back to its default."""
    with _with_runtime({"generation": {"temperature": None}}):
        assert await _drain(contexts) == ["tok"]
    assert captured[0]["temperature"] is None

    with _with_runtime({"generation": {"temperature": 0.0}}):
        assert await _drain(contexts) == ["tok"]
    assert captured[1]["temperature"] == 0.0


async def test_the_temperature_is_read_per_call_not_captured(
    monkeypatch: pytest.MonkeyPatch, contexts: list[ExpandedContext]
) -> None:
    """A runtime settings change between runs has to take effect; caching the
    value at import would silently ignore it — the same class of bug as
    reading an env-only field."""
    seen: list[Any] = []

    async def spy(**kwargs: Any) -> AsyncIterator[str]:
        seen.append(kwargs["temperature"])
        yield "tok"

    monkeypatch.setattr(generate_module, "stream_completion", spy)

    with _with_runtime({"generation": {"temperature": 0.0}}):
        await _drain(contexts)
    with _with_runtime({"generation": {"temperature": 0.7}}):
        await _drain(contexts)

    assert seen == [0.0, 0.7]


async def test_the_chitchat_and_library_branches_send_no_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only `stream_grounded_answer` was changed. The other two generator
    entry points pass no temperature, so they keep the provider default."""
    seen: list[dict[str, Any]] = []

    async def spy(**kwargs: Any) -> AsyncIterator[str]:
        seen.append(kwargs)
        yield "tok"

    monkeypatch.setattr(generate_module, "stream_completion", spy)

    from graph.generate import stream_chitchat_reply, stream_library_reply

    with _with_runtime({"generation": {"temperature": 0}}):
        async for _ in stream_chitchat_reply(
            litellm_model="openrouter/test/generator", message="hi", history=[], metadata={}
        ):
            pass
        async for _ in stream_library_reply(
            litellm_model="openrouter/test/generator",
            question="what do I have",
            names=["a.md"],
            history=[],
            metadata={},
        ):
            pass

    assert len(seen) == 2
    assert all("temperature" not in kwargs for kwargs in seen)
