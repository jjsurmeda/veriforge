"""Controller node tests (TRD §7 Deep row, §8): DecisionEngine mocked with
a fake Jev engine — no live model, per testing.md's decisions rule."""

from typing import Any

from decisions.engine import DecisionEngine
from graph.controller import controller_decide
from schemas.decisions import Answer, Question


class _FakeJev:
    def __init__(self, value: str, probability: float) -> None:
        self._value = value
        self._probability = probability

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        return {
            name: Answer(
                engine="jev",
                latency_ms=5,
                value=self._value,
                probability=self._probability,
                probabilities={self._value: self._probability},
            )
            for name in questions
        }


async def test_controller_sufficient_above_threshold() -> None:
    engine = DecisionEngine(jev=_FakeJev("sufficient", 0.9), mode="jev_only")
    sufficient, answer = await controller_decide(
        engine, run_id="r1", question="q", notes="evidence"
    )
    assert sufficient is True
    assert answer.value == "sufficient"


async def test_controller_need_more_is_not_sufficient() -> None:
    engine = DecisionEngine(jev=_FakeJev("need_more", 0.9), mode="jev_only")
    sufficient, _ = await controller_decide(engine, run_id="r1", question="q", notes="evidence")
    assert sufficient is False


async def test_controller_low_confidence_defaults_to_not_sufficient() -> None:
    """Even a 'sufficient' answer below the confidence floor is treated as
    need_more — same safe-default rule ingress applies to Choice answers."""
    engine = DecisionEngine(jev=_FakeJev("sufficient", 0.1), mode="jev_only")
    sufficient, _ = await controller_decide(engine, run_id="r1", question="q", notes="evidence")
    assert sufficient is False
