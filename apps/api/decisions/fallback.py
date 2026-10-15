"""Fallback engine (TRD §8): Haiku-class LiteLLM call with a JSON schema
derived from the same Question objects Jev receives.

Noul asks for a probability; Choice asks for a probability per option
(normalised to sum to 1); Score asks for a number in range. The prompt
carries the same state Jev would see, so per-engine thresholds — not
shared ones — gate downstream behaviour.
"""

import json
import logging
import re
import time
from typing import Any

from config import get_settings
from observability import tracing
from providers.llm import complete
from schemas.decisions import Answer, Choice, Noul, Question, Score

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class FallbackError(Exception):
    """The fallback LLM returned unparseable or out-of-schema output."""


# The output cap for one batched decide call, sized to the questions asked
# (KI-57). The response is one JSON object with one answer per question, each
# carrying its own reasoning, so its size is a function of the batch and a
# fixed cap is a truncation waiting for the batch that outgrows it — which is
# exactly what happened: the 4096 role cap was sized for the sufficiency call
# and the reranker's rubric, whose per-passage `Choice` answers carry a
# four-way distribution plus reasoning for up to 40 candidates, makes a bigger
# object still.
#
# Measured against the recorded shapes rather than guessed: the largest Noul
# answer in the entity-mismatch set is ~120 tokens of JSON with its reasoning,
# and the largest `Choice` answer (the rubric) ~200. The base covers the object
# and the keys; the per-question figures are what a long reasoning string costs.
FALLBACK_BASE_TOKENS = 512
FALLBACK_NUL_TOKENS = 320
FALLBACK_SCORE_TOKENS = 200
FALLBACK_CHOICE_TOKENS = 420


def fallback_max_tokens(questions: dict[str, Question]) -> int:
    """The cap one batch needs: sized to the questions, never below the role's.

    The floor is the `decision_fallback` role cap, so this only ever *raises* a
    cap — a batch small enough to fit the role's value is sent unchanged, and
    the role's own number stays the single place the base cap is configured.
    """
    total = FALLBACK_BASE_TOKENS
    for question in questions.values():
        if isinstance(question, Noul):
            total += FALLBACK_NUL_TOKENS
        elif isinstance(question, Choice):
            total += FALLBACK_CHOICE_TOKENS
        else:
            total += FALLBACK_SCORE_TOKENS
    role_cap = get_settings().llm_max_tokens.get("decision_fallback", 0)
    return max(total, int(role_cap))


def _render_prompt(state: str, questions: dict[str, Question]) -> str:
    lines = [
        "You are a structured decision engine. Answer every question below "
        "with strict JSON matching the schema described. No prose.",
        "",
        "[state]",
        state,
        "",
        "[questions]",
    ]
    for name, q in questions.items():
        if isinstance(q, Noul):
            lines.append(f"- {name} (noul): {q.prompt}")
            lines.append('  → {"probability": <0..1>, "reasoning": <str>}')
        elif isinstance(q, Choice):
            lines.append(f"- {name} (choice): {q.prompt}")
            lines.append(f"  options: {', '.join(q.options)}")
            if q.criteria:
                lines.append(f"  criteria: {q.criteria}")
            lines.append(
                '  → {"probabilities": {<option>: <0..1>, ...} summing to 1, "reasoning": <str>}'
            )
        elif isinstance(q, Score):
            lines.append(f"- {name} (score {q.min}..{q.max}): {q.prompt}")
            lines.append(f'  → {{"value": <{q.min}..{q.max}>, "reasoning": <str>}}')
    lines.append("")
    lines.append("Respond with a single JSON object keyed by question name.")
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    text = text.strip()
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def _parse_answers(
    payload: dict[str, Any], questions: dict[str, Question], latency_ms: int
) -> dict[str, Answer]:
    out: dict[str, Answer] = {}
    for name, q in questions.items():
        raw = payload.get(name)
        if not isinstance(raw, dict):
            raise FallbackError(f"missing or non-object answer for {name!r}")
        reasoning = raw.get("reasoning")
        try:
            if isinstance(q, Noul):
                probability = float(raw["probability"])
                if not 0.0 <= probability <= 1.0:
                    raise FallbackError(f"noul {name!r} out of range: {probability}")
                out[name] = Answer(
                    engine="fallback",
                    latency_ms=latency_ms,
                    value=probability,
                    probability=probability,
                    reasoning=reasoning,
                )
            elif isinstance(q, Choice):
                raw_probs = raw["probabilities"]
                if not isinstance(raw_probs, dict):
                    raise FallbackError(f"choice {name!r} probabilities not an object")
                total = sum(float(v) for v in raw_probs.values())
                if total <= 0:
                    raise FallbackError(f"choice {name!r} probabilities sum to {total}")
                probabilities = {str(k): float(v) / total for k, v in raw_probs.items()}
                missing = set(q.options) - set(probabilities)
                if missing:
                    raise FallbackError(f"choice {name!r} missing options {missing}")
                choice_value = max(probabilities.items(), key=lambda kv: kv[1])[0]
                out[name] = Answer(
                    engine="fallback",
                    latency_ms=latency_ms,
                    value=choice_value,
                    probability=probabilities[choice_value],
                    probabilities=probabilities,
                    reasoning=reasoning,
                )
            elif isinstance(q, Score):
                score_value = float(raw["value"])
                if not q.min <= score_value <= q.max:
                    raise FallbackError(f"score {name!r} out of range: {score_value}")
                out[name] = Answer(
                    engine="fallback",
                    latency_ms=latency_ms,
                    value=score_value,
                    probability=None,
                    reasoning=reasoning,
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise FallbackError(f"unparseable answer for {name!r}: {exc}") from exc
    return out


class FallbackEngine:
    """One fallback engine per process. `complete_fn` is injectable so
    tests can stub the LiteLLM call (testing.md: no live LLM calls).

    **An unusable reply is a batch problem, not a run problem (KI-57).**
    The recorded failure was a Jev socket timeout, then the fallback returning
    a non-JSON body (`Expecting value: line 1 column 1`), then the run failing
    with `decision_unavailable` — one unreadable reply ending a whole turn.
    Three things stop that repeating, in order:

    1. the output cap is sized to the batch (`fallback_max_tokens`), so the
       truncation that caused it has somewhere to go;
    2. an unparseable reply is retried once, which covers the transient shape
       (a connection cut mid-body, a provider that wrapped the object in prose);
    3. a reply still unreadable is retried as *halves of the batch*, which is
       the case a fixed cap cannot fix — a truncated object is truncated
       deterministically, so re-asking the same batch returns the same cut, and
       only a smaller object gets a complete answer.

    A single question that still fails is the end of the line: there is nothing
    smaller to split it into, and `DecisionEngine` turns that into the named
    `decision_unavailable`, which the graph stages degrade on rather than fail.
    """

    #: One retry of the *same* batch before any split (see the class docstring).
    ATTEMPTS_PER_BATCH = 2

    def __init__(self, complete_fn: Any = None) -> None:
        self._complete = complete_fn or complete

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        state_text = state if isinstance(state, str) else _state_to_text(state)
        stage = state.get("kind") if isinstance(state, dict) else None
        started = time.monotonic()

        def record(exc: BaseException) -> None:
            # The fallback runs through LiteLLM so its *generation*
            # was traced, but nothing said it was a decision or which one —
            # and a fallback that fails is exactly when that matters. The
            # span is recorded here so a degraded decision engine reads as a
            # degraded trace rather than as an absent one.
            tracing.record_decision_call(
                engine="fallback",
                decision_names=list(questions),
                stage=stage if isinstance(stage, str) else None,
                trace_id=tracing.current_trace_id(),
                latency_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )

        try:
            answers = await self._decide_batch(state_text, questions, started)
        except (FallbackError, json.JSONDecodeError) as exc:
            wrapped = exc if isinstance(exc, FallbackError) else FallbackError(
                f"fallback returned non-JSON: {exc}"
            )
            record(wrapped)
            raise wrapped from exc
        except Exception as exc:
            # A provider that times out, is refused, or dies mid-stream used
            # to escape as whatever litellm raised, which the graph then
            # reported as a generic `run_error` — indistinguishable from a bug
            # in our own code, and with no hint that the *decision engine* was
            # unreachable. Every failure of the fallback becomes a
            # FallbackError, which `DecisionEngine` turns into the named
            # `decision_unavailable` code.
            wrapped = FallbackError(f"fallback call failed: {type(exc).__name__}: {exc}")
            record(wrapped)
            raise wrapped from exc
        tracing.record_decision_call(
            engine="fallback",
            decision_names=list(questions),
            stage=stage if isinstance(stage, str) else None,
            trace_id=tracing.current_trace_id(),
            answers=answers,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return answers

    async def _decide_batch(
        self,
        state_text: str,
        questions: dict[str, Question],
        started: float,
    ) -> dict[str, Answer]:
        """One batch, retried at its own width and then halved until it fits.

        The recursion's only terminator is a single question: there is nothing
        smaller to split one into, so its failure is a real one and propagates.
        Every width above that is halved, all the way down — a single halving
        only rescues a batch that was twice too wide, which is not what
        truncation looks like (it truncates by however much it truncates by).
        """
        try:
            return await self._attempt(state_text, questions, started)
        except (FallbackError, json.JSONDecodeError):
            if len(questions) <= 1:
                raise
            logger.warning(
                "fallback could not answer a %d-question batch; splitting it",
                len(questions),
            )
        names = list(questions)
        half = len(names) // 2
        answers: dict[str, Answer] = {}
        for group in (names[:half], names[half:]):
            answers.update(
                await self._decide_batch(
                    state_text,
                    {name: questions[name] for name in group},
                    started,
                )
            )
        return answers

    async def _attempt(
        self, state_text: str, questions: dict[str, Question], started: float
    ) -> dict[str, Answer]:
        """One call and one retry of the same batch."""
        settings = get_settings()
        prompt = _render_prompt(state_text, questions)
        last: Exception | None = None
        for _ in range(self.ATTEMPTS_PER_BATCH):
            try:
                response = await self._complete(
                    litellm_model=settings.fallback_model,
                    messages=[{"role": "system", "content": prompt}],
                    metadata={"job": "decision_fallback", "role": "decision_fallback"},
                    # KI-57: ask for the JSON rather than hoping the prompt's
                    # "no prose" survives contact with a degraded provider, and
                    # size the cap to what this batch actually has to return.
                    max_tokens=fallback_max_tokens(questions),
                    response_format={"type": "json_object"},
                )
                latency_ms = int((time.monotonic() - started) * 1000)
                payload = json.loads(_strip_fence(response))
                if not isinstance(payload, dict):
                    raise FallbackError("fallback returned non-object JSON")
                return _parse_answers(payload, questions, latency_ms)
            except (FallbackError, json.JSONDecodeError) as exc:
                last = exc
        assert last is not None  # the loop ran at least once
        raise FallbackError(
            f"fallback returned unusable output after {self.ATTEMPTS_PER_BATCH} attempts: {last}"
        ) from last


def _state_to_text(state: dict[str, Any]) -> str:
    return "\n\n".join(f"[{key}]\n{value}" for key, value in state.items())
