"""Fallback engine output cap (KI-57): the largest batched decide response
must fit the decision_fallback role's cap, or every degraded-jev run of the
entity-mismatch set fails its item — the batched JSON truncated mid-string
at the same offset on every re-run. LiteLLM is faked (testing.md: no live
LLM calls)."""

import json

from config import get_settings
from decisions.fallback import FallbackEngine
from retrieval.context import count_tokens
from schemas.decisions import Noul

# The largest batch the system asks the fallback engine for is the
# post-sanitize sufficiency call with its per-passage entity questions
# (sufficient + relevance + one Noul per top-k passage). Twelve questions
# sits above that maximum and is the size the cap must cover.
N_QUESTIONS = 12


def _questions(n: int = N_QUESTIONS) -> dict[str, Noul]:
    return {f"entity_{i}": Noul(prompt=f"Is this passage about entity {i}?") for i in range(n)}


def _response(n: int = N_QUESTIONS) -> str:
    """A strict-JSON response with one answer per question, each carrying a
    realistic reasoning string. Sized so it exceeds the 512-token default
    cap: that is exactly the response the old cap truncated mid-JSON."""
    payload: dict[str, dict[str, float | str]] = {}
    for i in range(n):
        payload[f"entity_{i}"] = {
            "probability": round(0.5 + 0.02 * i, 2),
            "reasoning": "The passage discusses the named entity and its "
            "specifications, and the wording matches the question's entity "
            "throughout. " + f"Passage {i}: subject, value and citation all agree. ",
        }
    return json.dumps(payload)


async def test_a_twelve_question_batch_round_trips() -> None:
    """The largest real batch must come back complete when jev is down:
    every question answered by the fallback engine, no FallbackError."""
    questions = _questions()

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str], **_: object
    ) -> str:
        assert metadata == {"job": "decision_fallback", "role": "decision_fallback"}
        assert litellm_model == get_settings().fallback_model
        return _response()

    engine = FallbackEngine(complete_fn=fake_complete)
    answers = await engine.decide(state="[query]\nentity question", questions=questions)

    assert len(answers) == N_QUESTIONS
    for name in questions:
        assert name in answers
        assert answers[name].engine == "fallback"
        assert 0.0 <= answers[name].probability <= 1.0


async def test_the_fallback_cap_covers_the_twelve_question_response() -> None:
    """KI-57: the 12-answer JSON of the largest batch exceeds the 512-token
    default that used to truncate it mid-JSON, and fits the
    decision_fallback role's cap. Mutation: delete the role entry and the
    cap falls back to the default — the second assert fails."""
    settings = get_settings()
    tokens = count_tokens(_response())
    assert tokens > settings.llm_default_max_tokens, (
        f"fixture response must exceed the old default cap ({settings.llm_default_max_tokens}) "
        f"to prove the truncation, got {tokens} tokens"
    )
    assert tokens <= settings.llm_max_tokens["decision_fallback"], (
        f"12-answer response is {tokens} tokens; the decision_fallback cap "
        f"({settings.llm_max_tokens['decision_fallback']}) must cover it"
    )
