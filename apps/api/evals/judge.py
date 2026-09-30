"""Post-hoc LLM judge (TRD §10 "Async scoring (worker)", TRD §15).

Slice 6: the interim single-call judge's TODO(slice-6) is resolved —
faithfulness and citation precision are now computed by the real Reviewer
(graph/review.py). What remains here is the *different mechanism* the TRD
keeps separate: context precision, context recall (when a reference
exists) and answer relevance, judged after the run and pushed to Langfuse
as trace scores. They never block delivery and never gate evals.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from prompts.load import load_prompt
from providers.llm import complete


@dataclass(frozen=True)
class JudgeScores:
    context_precision: float | None
    context_recall: float | None
    answer_relevance: float | None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """The judge (Haiku 4.5) appends prose after the fenced JSON
    ("**Justification:** ..."), so a whole-string match fails and every
    field lands null (D2 item 2b, captured raw responses 2026-10-01).
    Decode the first JSON object wherever it sits in the response."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _field(data: dict[str, Any], name: str) -> float | None:
    """One missing or malformed field must not null the other two."""
    try:
        return float(data[name])
    except (KeyError, TypeError, ValueError):
        return None


def parse_judge_response(response: str) -> JudgeScores | None:
    data = _extract_json_object(response.strip())
    if data is None:
        return None
    scores = JudgeScores(
        context_precision=_field(data, "context_precision"),
        context_recall=_field(data, "context_recall"),
        answer_relevance=_field(data, "answer_relevance"),
    )
    if all(value is None for value in vars(scores).values()):
        return None
    return scores


async def judge_answer(
    *,
    question: str,
    reference_answer: str,
    answer: str,
    passages: list[str],
    small_model: str,
) -> JudgeScores | None:
    """One structured judge call per item; returns None on unparseable output."""
    numbered = "\n\n".join(f"[Passage {i + 1}]\n{text}" for i, text in enumerate(passages))
    prompt = (
        load_prompt("eval_judge.md")
        .replace("{question}", question)
        .replace("{reference}", reference_answer or "(no reference answer)")
        .replace("{answer}", answer)
        .replace("{passages}", numbered or "(no passages were retrieved)")
    )
    response = await complete(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": question}],
        metadata={"job": "eval_judge", "role": "async_judge"},
    )
    return parse_judge_response(response)
