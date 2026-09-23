"""Suggested follow-ups (CH-9, TRD §10 "in parallel with review"): one
small-LLM call producing 3 questions grounded in retrieved-but-unused
chunks — contexts the answer did not cite. No unused contexts, no
suggestions."""

import json
import logging
import re
from typing import Any

from prompts.load import load_prompt
from providers.llm import complete
from retrieval.expand import ExpandedContext

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_suggestions(response: str) -> list[str]:
    match = _FENCE_RE.match(response.strip())
    text = match.group(1).strip() if match is not None else response.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    questions = data.get("questions", []) if isinstance(data, dict) else []
    return [q for q in questions if isinstance(q, str) and q.strip()][:3]


async def generate_suggestions(
    *,
    question: str,
    answer: str,
    contexts: list[ExpandedContext],
    cited_ns: list[int],
    small_model: str,
    complete_fn: Any = complete,
) -> list[str]:
    unused = [context for n, context in enumerate(contexts, start=1) if n not in cited_ns]
    if not unused:
        return []
    prompt = (
        load_prompt("suggestions.md")
        .replace("{question}", question)
        .replace("{answer}", answer)
        .replace(
            "{sources}",
            "\n\n".join(f"[{i + 1}] {c.context_text[:1500]}" for i, c in enumerate(unused)),
        )
    )
    response = await complete_fn(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}],
        metadata={"job": "suggestions"},
    )
    return parse_suggestions(response)
