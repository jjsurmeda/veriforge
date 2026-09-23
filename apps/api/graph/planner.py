"""Planner node (TRD §7 Deep row): breaks the question into 2-5
sub-questions with dependencies. Planning is generation, not a
routing/classification/scoring/verification decision, so it calls the
LLM directly via `providers.llm.complete` rather than DecisionEngine
(CLAUDE.md non-negotiable)."""

import json
import logging

from graph.rewrite import CompleteFn
from prompts.load import load_prompt
from schemas.events import SubQuestion

logger = logging.getLogger(__name__)

MIN_SUB_QUESTIONS = 2
MAX_SUB_QUESTIONS = 5


def _fallback_plan(question: str) -> list[SubQuestion]:
    return [SubQuestion(id="q1", question=question, depends_on=[])]


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()


def _parse_plan(raw: str, question: str) -> list[SubQuestion]:
    try:
        rows = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError):
        return _fallback_plan(question)
    if not isinstance(rows, list) or not rows:
        return _fallback_plan(question)

    sub_questions: list[SubQuestion] = []
    seen_ids: set[str] = set()
    for row in rows[:MAX_SUB_QUESTIONS]:
        if not isinstance(row, dict):
            continue
        sub_id = str(row.get("id", "")).strip()
        text = str(row.get("question", "")).strip()
        if not sub_id or not text or sub_id in seen_ids:
            continue
        depends_on = [
            str(d) for d in row.get("depends_on", []) if isinstance(d, str) and d != sub_id
        ]
        seen_ids.add(sub_id)
        sub_questions.append(SubQuestion(id=sub_id, question=text, depends_on=depends_on))

    if len(sub_questions) < MIN_SUB_QUESTIONS:
        return _fallback_plan(question)
    # Drop dependencies on ids that never made it into the plan (dropped
    # for being malformed) — a dangling dependency would stall a hop forever.
    valid_ids = {sq.id for sq in sub_questions}
    return [
        SubQuestion(
            id=sq.id, question=sq.question, depends_on=[d for d in sq.depends_on if d in valid_ids]
        )
        for sq in sub_questions
    ]


async def plan_question(
    question: str, *, small_model: str, complete_fn: CompleteFn
) -> list[SubQuestion]:
    # plan.md's example contains literal JSON braces, so .format() would
    # misparse them as placeholders — plain substitution instead.
    prompt = load_prompt("plan.md").replace("{question}", question)
    try:
        response = await complete_fn(
            litellm_model=small_model,
            messages=[{"role": "system", "content": prompt}],
            metadata={},
        )
    except Exception:
        logger.exception("planner call failed, falling back to single sub-question")
        return _fallback_plan(question)
    return _parse_plan(response, question)


def _parse_followup(raw: str) -> str | None:
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    text = str(data.get("question", "")).strip()
    return text or None


async def generate_followup(
    question: str, notes: str, *, small_model: str, complete_fn: CompleteFn, next_id: str
) -> SubQuestion | None:
    """Called when the Controller says `need_more` but the Planner's
    upfront plan is fully answered (TRD §7/§8: the Controller's verdict is
    supposed to drive the next sub-question, not just gate stopping) —
    returns None (caller should abstain) only if this call itself fails."""
    prompt = (
        load_prompt("plan_followup.md")
        .replace("{question}", question)
        .replace("{notes}", notes)
    )
    try:
        response = await complete_fn(
            litellm_model=small_model,
            messages=[{"role": "system", "content": prompt}],
            metadata={},
        )
    except Exception:
        logger.exception("followup planner call failed")
        return None
    text = _parse_followup(response)
    if text is None:
        return None
    return SubQuestion(id=next_id, question=text, depends_on=[])
