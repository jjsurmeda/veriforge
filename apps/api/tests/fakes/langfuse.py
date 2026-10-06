"""Fake Langfuse client for tests.

Records every span/generation/score the code under test asks for, so a test
can assert on *what was traced* without a network call or a key
(testing.md: tests never reach a live provider; the fake is also what lets a
test assert that a tracing failure cannot fail a run).
"""

from __future__ import annotations

from typing import Any


class FakeSpan:
    def __init__(
        self,
        name: str,
        trace_id: str | None,
        metadata: dict[str, Any] | None,
        input: Any,
    ) -> None:
        self.name = name
        self.trace_id = trace_id
        self.metadata = dict(metadata or {})
        self.input = input
        self.output: Any = None
        self.level: str | None = None
        self.status_message: str | None = None
        self.ended = False
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> FakeSpan:
        self.updates.append(kwargs)
        if kwargs.get("metadata"):
            self.metadata.update(kwargs["metadata"])
        if "output" in kwargs:
            self.output = kwargs["output"]
        if "level" in kwargs:
            self.level = kwargs["level"]
        if "status_message" in kwargs:
            self.status_message = kwargs["status_message"]
        return self

    def end(self, **kwargs: Any) -> FakeSpan:
        self.ended = True
        return self


class FakeLangfuse:
    """A stand-in for `langfuse.Langfuse`.

    `raises` makes every method raise, which is how the "tracing must never
    fail a run" tests prove that claim instead of asserting it in a comment.
    """

    def __init__(self, raises: bool = False) -> None:
        self.spans: list[FakeSpan] = []
        self.scores: list[dict[str, Any]] = []
        self.flushes = 0
        self.raises = raises
        self.host: str | None = None
        self.public_key: str | None = None

    def _check(self) -> None:
        if self.raises:
            raise RuntimeError("langfuse is down")

    def span(
        self,
        *,
        name: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        input: Any = None,
        start_time: Any = None,
        **kwargs: Any,
    ) -> FakeSpan:
        self._check()
        handle = FakeSpan(name or "", trace_id, metadata, input)
        self.spans.append(handle)
        return handle

    def score(self, **kwargs: Any) -> None:
        self._check()
        self.scores.append(kwargs)

    def flush(self) -> None:
        self._check()
        self.flushes += 1

    # --- assertions helpers ---

    def names(self) -> list[str]:
        return [span.name for span in self.spans]

    def find(self, name: str) -> FakeSpan | None:
        for span in self.spans:
            if span.name == name:
                return span
        return None