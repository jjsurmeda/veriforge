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

import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from config import get_settings
from retrieval.context import count_tokens
from schemas.decisions import Answer, Choice, Noul, Question, Score

logger = logging.getLogger(__name__)


class JevError(Exception):
    """Timeout, HTTP error, or unparseable response from the Jev endpoint."""


def _question_spec(q: Question) -> dict[str, Any]:
    if isinstance(q, Noul):
        return {"type": "noul", "prompt": q.prompt}
    if isinstance(q, Choice):
        return {
            "type": "choice",
            "prompt": q.prompt,
            "options": q.options,
            "criteria": q.criteria,
        }
    if isinstance(q, Score):
        return {"type": "score", "prompt": q.prompt, "min": q.min, "max": q.max}
    raise TypeError(f"unknown question type: {type(q).__name__}")


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


def _parse_answer(name: str, q: Question, raw: dict[str, Any], latency_ms: int) -> Answer:
    reasoning = raw.get("reasoning")
    try:
        if isinstance(q, Noul):
            probability = float(raw["probability"])
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
            choice_value = str(raw.get("value") or argmax)
            return Answer(
                engine="jev",
                latency_ms=latency_ms,
                value=choice_value,
                probability=probabilities.get(choice_value),
                probabilities=probabilities,
                reasoning=reasoning,
            )
        if isinstance(q, Score):
            score_value = float(raw["value"])
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
        if not settings.openrouter_api_key:
            raise JevError("OPENROUTER_API_KEY not set")
        payload = {
            "model": settings.jev_model,
            "state": _truncate_state(state, settings.jev_max_state_tokens),
            "questions": {name: _question_spec(q) for name, q in questions.items()},
        }
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        started = time.monotonic()
        try:
            if self._client is not None:
                response = await self._client.post(
                    settings.openrouter_systemone_url,
                    json=payload,
                    headers=headers,
                    timeout=settings.jev_timeout_ms / 1000,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=settings.jev_timeout_ms / 1000
                ) as client:
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
        try:
            data = response.json()
            answers = data["answers"]
        except (ValueError, KeyError) as exc:
            raise JevError(f"jev bad payload: {exc}") from exc
        return {
            name: _parse_answer(name, q, answers.get(name, {}), latency_ms)
            for name, q in questions.items()
        }
