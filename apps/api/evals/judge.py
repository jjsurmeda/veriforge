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

from prompts.load import load_prompt
from providers.llm import complete


@dataclass(frozen=True)
class JudgeScores:
    context_precision: float | None
    context_recall: float | None
    answer_relevance: float | None


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
            context_precision=float(data["context_precision"]),
            context_recall=float(data["context_recall"]),
            answer_relevance=float(data["answer_relevance"]),
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
