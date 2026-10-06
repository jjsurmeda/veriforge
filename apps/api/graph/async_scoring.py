"""Async scoring worker (TRD §10 "Async scoring (worker)"): after a run
completes, judge context precision, context recall and answer relevance
and push them to Langfuse as trace scores. Fire-and-forget — never blocks
delivery, never touches the inline Reviewer's claim verification.
"""

import asyncio
import logging
import random
from uuid import UUID

from config import get_settings
from evals.judge import judge_answer
from observability import tracing
from quota.usage import get_usage_context
from retrieval.expand import ExpandedContext
from runtime import runtime_value

logger = logging.getLogger(__name__)

_SMALL_MODEL = "openrouter/anthropic/claude-haiku-4.5"


def _push_scores(trace_id: str, scores: dict[str, float]) -> None:
    # `observability.tracing` owns the client, so the host is configured the
    # same way here as for the spans. This used to build `Langfuse()` with no
    # arguments, which read LANGFUSE_HOST from the environment — a variable
    # nothing in the app ever set (KI-21), so scores went to the EU default
    # and failed there exactly as the generations did.
    tracing.score(trace_id, scores)


async def score_run_async(
    *,
    run_id: UUID,
    question: str,
    answer: str,
    contexts: list[ExpandedContext],
    reference_answer: str | None = None,
) -> None:
    if random.random() > float(runtime_value("trace_sample_rate", 1.0)):  # noqa: S311
        return
    usage = get_usage_context()
    if not get_settings().openrouter_api_key and (usage is None or not usage.api_keys):
        return
    try:
        judged = await judge_answer(
            question=question,
            reference_answer=reference_answer or "",
            answer=answer,
            passages=[context.context_text for context in contexts],
            small_model=_SMALL_MODEL,
        )
    except Exception:
        logger.exception("async scoring judge failed", extra={"run_id": str(run_id)})
        return
    if judged is None:
        return
    scores: dict[str, float] = {}
    if judged.context_precision is not None:
        scores["context_precision"] = judged.context_precision
    if judged.context_recall is not None and reference_answer:
        scores["context_recall"] = judged.context_recall
    if judged.answer_relevance is not None:
        scores["answer_relevance"] = judged.answer_relevance
    if not scores:
        return
    try:
        await asyncio.to_thread(_push_scores, str(run_id), scores)
    except Exception:
        logger.exception("langfuse score push failed", extra={"run_id": str(run_id)})
