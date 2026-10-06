"""Jev engine client (TRD §8).

POSTs to OpenRouter System One (`/api/v1/systemone`) with model
`typesafe/jev-1.13` pinned. Several questions per call; state kept under
`jev_max_state_tokens` to leave headroom in the 32K window. 2 s timeout
per call.

The response format is one answer per question name:
```json
{
  "answers": {
    "<name>": {
      "value": <bool|str|number>,
      "probability": <float, for noul/choice>,
      "probabilities": {<option>: <float>, ...},
      "reasoning": "<native reasoning text, optional>"
    }
  }
}
```

Tests use recorded fixtures from `tests/fixtures/jev/` — no live calls.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from config import get_settings
from observability import tracing
from quota.usage import get_usage_context
from retrieval.context import count_tokens
from schemas.decisions import Answer, Choice, Noul, Question, Score

logger = logging.getLogger(__name__)

# Eval-only seam (KI-18, D2 2c): Jev uses raw httpx, not litellm, so
# `evals.attribution.record_generation_ids` could never see Jev time and
# every Jev millisecond was counted as "our overhead". When the sink is
# set, each call's OpenRouter `x-generation-id` header is reported, the
# same way litellm calls are recorded. Production never sets the sink.
generation_id_sink: Callable[[str], None] | None = None


class JevError(Exception):
    """Timeout, HTTP error, or unparseable response from the Jev endpoint."""


def _question_spec(q: Question) -> dict[str, Any]:
    # Wire format is OpenRouter System One's, not ours: "instructions" not
    # "prompt", and options live as keys of a "criteria" record (choice) or
    # a >=1-item legend array (score) — the API rejects the shape our
    # internal Question models use directly.
    if isinstance(q, Noul):
        return {"type": "noul", "instructions": q.prompt}
    if isinstance(q, Choice):
        criteria = {opt: (q.criteria or opt) for opt in q.options}
        return {"type": "choice", "instructions": q.prompt, "criteria": criteria}
    if isinstance(q, Score):
        return {
            "type": "score",
            "instructions": q.prompt,
            "criteria": [f"low end ({q.min})", f"high end ({q.max})"],
        }
    raise TypeError(f"unknown question type: {type(q).__name__}")


def _scale_score(fraction: float, q: Score) -> float:
    """Score answers come back as a 0..1 fraction across the criteria
    legend, not in [q.min, q.max] — scale to the question's declared range."""
    return q.min + fraction * (q.max - q.min)


def _truncate_state(state: dict[str, Any] | str, max_tokens: int) -> str:
    text = state if isinstance(state, str) else _state_to_text(state)
    if count_tokens(text) <= max_tokens:
        return text
    # Rough 4-chars-per-token slice; cheap and sufficient — the head of
    # the state is the most recent question context, the tail is history.
    approx_chars = max_tokens * 4
    return text[:approx_chars]


def _state_to_text(state: dict[str, Any]) -> str:
    return "\n\n".join(f"[{key}]\n{value}" for key, value in state.items())


def _stage_of(state: dict[str, Any] | str) -> str | None:
    """The pipeline stage this decision belongs to, for the span metadata.

    The same `kind` key `decisions/engine.py` reads for `DecisionCall.stage`,
    so a Jev span carries the same stage name the decision events and the
    UI already show rather than a second vocabulary. None when the state is
    a bare string, which is what the engine's own tests pass.
    """
    if isinstance(state, dict):
        value = state.get("kind")
        return value if isinstance(value, str) else None
    return None


def _parse_answer(name: str, q: Question, raw: dict[str, Any], latency_ms: int) -> Answer:
    reasoning = raw.get("reasoning")
    try:
        if isinstance(q, Noul):
            probability = float(raw["noul"])
            return Answer(
                engine="jev",
                latency_ms=latency_ms,
                value=probability,
                probability=probability,
                reasoning=reasoning,
            )
        if isinstance(q, Choice):
            probabilities = {str(k): float(v) for k, v in raw["probabilities"].items()}
            argmax = max(probabilities.items(), key=lambda kv: kv[1])[0]
            choice_value = str(raw.get("choice") or argmax)
            return Answer(
                engine="jev",
                latency_ms=latency_ms,
                value=choice_value,
                probability=probabilities.get(choice_value),
                probabilities=probabilities,
                reasoning=reasoning,
            )
        if isinstance(q, Score):
            score_value = _scale_score(float(raw["score"]), q)
            return Answer(
                engine="jev",
                latency_ms=latency_ms,
                value=score_value,
                probability=None,
                reasoning=reasoning,
            )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise JevError(f"unparseable Jev answer for {name!r}: {exc}") from exc
    raise TypeError(f"unknown question type: {type(q).__name__}")


class JevClient:
    """One Jev engine instance per process; breaker lives outside (engine.py)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        settings = get_settings()
        resolved_model = settings.jev_model
        api_key = settings.openrouter_api_key
        usage_context = get_usage_context()
        if usage_context is not None:
            resolved_model = await usage_context.resolve_model(resolved_model, "decision_engine")
            api_key = usage_context.api_key_for(resolved_model) or api_key
        model = resolved_model.removeprefix("openrouter/")
        if not api_key:
            raise JevError("OPENROUTER_API_KEY not set")
        payload = {
            "model": model,
            "state": _truncate_state(state, settings.jev_max_state_tokens),
            "questions": {name: _question_spec(q) for name, q in questions.items()},
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        started = time.monotonic()
        # Every exit from here records a span, success or failure: a Jev
        # call that timed out is the thing an operator is looking for, and
        # it is invisible in the trace otherwise. `latency_ms` is computed
        # in the `finally` so the failure path reports how long it waited,
        # which is the number the 2 s timeout is judged against.
        latency_ms = 0
        error: str | None = None
        try:
            try:
                if self._client is not None:
                    response = await self._client.post(
                        settings.openrouter_systemone_url,
                        json=payload,
                        headers=headers,
                        timeout=settings.jev_timeout_ms / 1000,
                    )
                else:
                    async with httpx.AsyncClient(timeout=settings.jev_timeout_ms / 1000) as client:
                        response = await client.post(
                            settings.openrouter_systemone_url,
                            json=payload,
                            headers=headers,
                        )
            except httpx.HTTPError as exc:
                raise JevError(f"jev http error: {exc}") from exc
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.status_code != 200:
                raise JevError(f"jev status {response.status_code}: {response.text[:200]}")
            if generation_id_sink is not None:
                generation_id = response.headers.get("x-generation-id")
                if generation_id:
                    generation_id_sink(generation_id)
            try:
                data = response.json()
                answers = data["answers"]
            except (ValueError, KeyError) as exc:
                raise JevError(f"jev bad payload: {exc}") from exc

            if usage_context is not None:
                await usage_context.record_call(
                    model_id=model,
                    role="decision_engine",
                    tokens_in=count_tokens(json.dumps(payload)),
                    tokens_out=count_tokens(json.dumps(data)),
                )
            parsed: dict[str, Answer] = {}
            try:
                for name, question in questions.items():
                    parsed[name] = _parse_answer(name, question, answers.get(name, {}), latency_ms)
                return parsed
            finally:
                # Recorded in a `finally` so a partial or unparseable batch is
                # still a span: an operator reading the trace needs to see
                # that the call happened and failed, which is the opposite of
                # what "no span" looks like. Never raises.
                tracing.record_decision_call(
                    engine="jev",
                    decision_names=list(questions),
                    stage=_stage_of(state),
                    trace_id=tracing.current_trace_id(),
                    answers=parsed,
                    latency_ms=latency_ms,
                    error=error,
                )
        except JevError as exc:
            error = str(exc)
            tracing.record_decision_call(
                engine="jev",
                decision_names=list(questions),
                stage=_stage_of(state),
                trace_id=tracing.current_trace_id(),
                latency_ms=int((time.monotonic() - started) * 1000),
                error=error,
            )
            raise
