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
from providers.llm import complete
from schemas.decisions import Answer, Choice, Noul, Question, Score

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class FallbackError(Exception):
    """The fallback LLM returned unparseable or out-of-schema output."""


def _schema_for(questions: dict[str, Question]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, q in questions.items():
        if isinstance(q, Noul):
            properties[name] = {
                "type": "object",
                "properties": {
                    "probability": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string"},
                },
                "required": ["probability"],
            }
        elif isinstance(q, Choice):
            properties[name] = {
                "type": "object",
                "properties": {
                    "probabilities": {
                        "type": "object",
                        "properties": {opt: {"type": "number"} for opt in q.options},
                        "required": list(q.options),
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["probabilities"],
            }
        elif isinstance(q, Score):
            properties[name] = {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "minimum": q.min, "maximum": q.max},
                    "reasoning": {"type": "string"},
                },
                "required": ["value"],
            }
    return {
        "type": "object",
        "properties": properties,
        "required": list(questions.keys()),
    }


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
    tests can stub the LiteLLM call (testing.md: no live LLM calls)."""

    def __init__(self, complete_fn: Any = None) -> None:
        self._complete = complete_fn or complete

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        settings = get_settings()
        state_text = state if isinstance(state, str) else _state_to_text(state)
        prompt = _render_prompt(state_text, questions)
        started = time.monotonic()
        response = await self._complete(
            litellm_model=settings.fallback_model,
            messages=[{"role": "system", "content": prompt}],
            metadata={"job": "decision_fallback", "role": "decision_fallback"},
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(_strip_fence(response))
        except json.JSONDecodeError as exc:
            raise FallbackError(f"fallback returned non-JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise FallbackError("fallback returned non-object JSON")
        return _parse_answers(payload, questions, latency_ms)


def _state_to_text(state: dict[str, Any]) -> str:
    return "\n\n".join(f"[{key}]\n{value}" for key, value in state.items())
