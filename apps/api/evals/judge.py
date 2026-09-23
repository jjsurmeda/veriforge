"""Interim eval judges (TRD §15).

TODO(slice-6): faithfulness here is a single-shot LLM-judge score
(answer + citations → judge call). Slice 6's Reviewer replaces this with
real claim-level extraction/verdict scoring (TRD §10) — replace this file,
don't add to it. The interim judge also emits citation precision and
context precision/recall so the slice-3 gate has the full metric set.
"""

import json
import re
from dataclasses import dataclass

from prompts.load import load_prompt
from providers.llm import complete


@dataclass(frozen=True)
class JudgeScores:
    faithfulness: float | None
    citation_precision: float | None
    context_precision: float | None
    context_recall: float | None


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_judge_response(response: str) -> JudgeScores | None:
    text = response.strip()
    match = _FENCE_RE.match(text)
    if match is not None:
        text = match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    try:
        return JudgeScores(
            faithfulness=float(data["faithfulness"]),
            citation_precision=float(data["citation_precision"]),
            context_precision=float(data["context_precision"]),
            context_recall=float(data["context_recall"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


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
        .replace("{reference}", reference_answer or "(no reference — item expects abstention)")
        .replace("{answer}", answer)
        .replace("{passages}", numbered or "(no passages were retrieved)")
    )
    response = await complete(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": question}],
        metadata={"job": "eval_judge"},
    )
    return parse_judge_response(response)
