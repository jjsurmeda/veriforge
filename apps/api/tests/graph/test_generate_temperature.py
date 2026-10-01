"""Generator temperature plumbing (KI-32).

The generator reads `generation_temperature` from settings and passes it to
`stream_completion`. Unset must send nothing at all, so generation is
unchanged from before the setting existed; the provider-level half of the
contract (absent key vs. forwarded value, and the failover hop) is in
tests/providers/test_llm_limits.py.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from config import Settings
from graph import generate as generate_module
from graph.generate import stream_grounded_answer
from retrieval.expand import ExpandedContext


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
    captured: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, contexts: list[ExpandedContext]
) -> None:
    """The default is the point: unset means "send nothing", so the request is
    identical to the one made before this setting existed."""
    monkeypatch.setattr(generate_module, "get_settings", lambda: Settings())

    assert await _drain(contexts) == ["tok"]
    assert Settings().generation_temperature is None
    assert captured[0]["temperature"] is None


async def test_generator_forwards_a_configured_temperature(
    captured: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, contexts: list[ExpandedContext]
) -> None:
    monkeypatch.setattr(
        generate_module, "get_settings", lambda: Settings(generation_temperature=0.2)
    )

    assert await _drain(contexts) == ["tok"]
    assert captured[0]["temperature"] == 0.2


async def test_the_temperature_setting_is_read_per_call_not_captured(
    monkeypatch: pytest.MonkeyPatch, contexts: list[ExpandedContext]
) -> None:
    """A runtime settings change between runs has to take effect; caching the
    value at import would silently ignore it."""
    seen: list[Any] = []
    value: float = 0.0

    async def spy(**kwargs: Any) -> AsyncIterator[str]:
        seen.append(kwargs["temperature"])
        yield "tok"

    monkeypatch.setattr(generate_module, "stream_completion", spy)
    monkeypatch.setattr(
        generate_module, "get_settings", lambda: Settings(generation_temperature=value)
    )

    await _drain(contexts)
    value = 0.7
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
    monkeypatch.setattr(generate_module, "get_settings", lambda: Settings(generation_temperature=0))

    from graph.generate import stream_chitchat_reply, stream_library_reply

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
