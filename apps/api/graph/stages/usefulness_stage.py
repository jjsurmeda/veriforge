"""IsUse (ADR-006, accepted 2026-10-17): does the answer answer the question?

The evidence floor before generation decides whether the evidence could yield
an answer; it says nothing about whether the generated answer actually gives
what the question asked for. That is what this stage checks, after generation,
on the grounded answer and its sources — Self-RAG's IsUse, the third critique
the pipeline used to lack (IsRel ≈ the rubric grade, IsSup = the reviewer,
IsUse here).

**Both the product's Auto path (`graph/stages/run_auto.py`) and the eval
harness (`evals/runner.py`) call this stage**, so the eval measures what the
product does; the probe that found the signal (`.data/evals/
isuse-probe-a03a3a8.json`) bypassed the product, so its numbers are evidence,
not a substitute.

Outage rule (KI-57, fail-closed): an unreachable decision layer is treated as
a failing check, never a passing one — the run declines with the normal TR-4
template and still ends through the shared tail, a completed run with an
abstained message, never `run.failed`. The threshold table lives beside the
`is_use` key in `decisions/thresholds.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from decisions import threshold
from decisions.engine import DecisionUnavailable, EngineProtocol
from graph.abstain import build_abstain_event, build_abstain_template, stream_abstention
from schemas.decisions import Answer, Noul
from schemas.events import Decision

if TYPE_CHECKING:  # retrieval.expand imports the DB stack; typing only here.
    from collections.abc import Awaitable, Callable, Sequence

    from retrieval.expand import ExpandedContext

logger = logging.getLogger(__name__)

IS_USE_NAME = "is_use"
# The state dict's `kind` is what DecisionCall.stage records, and the golden
# tests key their scripts on it. Matches the probe's own call verbatim.
KIND = "isuse"

IS_USE_THRESHOLD_KEY = "is_use"

# The probe's question, byte for byte: `.data/evals/isuse-probe-a03a3a8.json`
# was measured with it, and both thresholds here (`is_use`) and the evidence
# floor were derived from that data — changing this wording invalidates them.
IS_USE_PROMPT = (
    "Question: {q}\n\nAnswer: {a}\n\nSources:\n{s}\n\n"
    "Does the answer directly answer the question that was asked, using what the sources "
    "state? Answer no if it talks about related facts but does not give what the question "
    "asks for, or if the sources do not contain what the question asks for."
)

# The probe truncated each source at these chars, so the truncation is part of
# the measurement the threshold was derived from.
_SOURCE_CHARS = 1200


@dataclass
class UsefulnessOutcome:
    """What the stage decided, and the trace row that says so.

    `state` is `"pass"`, `"fail"` (the engine judged the answer not useful),
    or `"unavailable"` (the decision layer was unreachable, treated as
    failing — KI-57, fail-closed).
    """

    state: str
    value: float | None = None
    engine: str = "jev"
    threshold: float | None = None
    # The row appended to `decision_events` (the eval export reads that list).
    # On the product path an *answered* call's bus trace row is the engine
    # emitter's job; this row is what a run whose check never got an answer
    # still carries, published once by the caller.
    decision_row: Decision | None = None


def is_use_question(
    question: str, answer: str, contexts: Sequence[ExpandedContext]
) -> Noul:
    """The IsUse Noul over the question as asked, the generated answer and the
    sources. Sources are truncated exactly as the probe truncated them,
    because the threshold was calibrated over those bytes."""
    sources = "\n".join(
        f"[{i}] {c.context_text[:_SOURCE_CHARS]}" for i, c in enumerate(contexts, 1)
    )
    return Noul(prompt=IS_USE_PROMPT.format(q=question, a=answer, s=sources))


async def usefulness_decline(
    run_id: str,
    contexts: Sequence[ExpandedContext],
    *,
    question: str,
    litellm_model: str,
    metadata: dict[str, str],
) -> str:
    """The TR-4 found/missing decline that replaces a failed answer, in the
    question's language (KI-95): `stream_abstention` keeps an English or
    undetectable question as the fixed template with no model call and
    translates otherwise; a translation failure falls back to the English
    template, it never fails the run.

    The same fixed template a pre-generation abstention renders — plain text,
    no citations (KI-25) — over what was retrieved.
    """
    abstain = build_abstain_event(
        run_id, [context.chunk for context in contexts], offered_actions=["web", "deep"]
    )
    # What is missing is named from the check that failed, not from the
    # evidence: the sources were retrieved, the drafted answer just did not
    # give what the question asked for from them.
    abstain.missing_summary = (
        "The retrieved sources do not directly state what the question "
        "asks for, so the drafted answer was not delivered."
    )
    try:
        text = "".join(
            [
                t
                async for t in stream_abstention(
                    abstain, litellm_model=litellm_model, question=question, metadata=metadata
                )
            ]
        )
    except Exception:
        logger.warning("IsUse decline translation failed; English template", exc_info=True)
        return build_abstain_template(abstain)
    return text or build_abstain_template(abstain)


async def run_usefulness(
    engine: EngineProtocol,
    *,
    run_id: str,
    question: str,
    answer: str,
    contexts: Sequence[ExpandedContext],
    decisions: list[Decision] | None = None,
    on_unavailable: Callable[[Decision], Awaitable[None]] | None = None,
) -> UsefulnessOutcome:
    """Ask IsUse once. Appends the trace row to `decisions` when given, and
    publishes the outage row through `on_unavailable` when the engine could
    not answer at all (an answered call's bus row is the engine emitter's
    job — publishing here too would double it).

    Fail-closed (KI-57): an outage reads to the caller exactly like a fail;
    only the trace row and the log distinguish them.
    """
    floor: float = threshold(IS_USE_THRESHOLD_KEY, "jev")
    try:
        answers = await engine.decide(
            state={"run_id": run_id, "kind": KIND},
            questions={IS_USE_NAME: is_use_question(question, answer, contexts)},
        )
    except DecisionUnavailable as exc:
        logger.warning(
            "decision layer unavailable at %s (%s); the answer declines as unverified",
            KIND,
            exc,
        )
        row = _unavailable_row(run_id)
        if decisions is not None:
            decisions.append(row)
        if on_unavailable is not None:
            await on_unavailable(row)
        return UsefulnessOutcome(
            state="unavailable",
            value=None,
            engine="unavailable",
            threshold=None,
            decision_row=row,
        )
    is_use = answers[IS_USE_NAME]
    # On the fallback's scale when the fallback answered: every threshold is
    # keyed by engine (decisions/thresholds.py).
    floor = threshold(IS_USE_THRESHOLD_KEY, "fallback" if is_use.engine == "fallback" else "jev")
    row = _decision_row(run_id, is_use, floor)
    if decisions is not None:
        decisions.append(row)
    return UsefulnessOutcome(
        state="pass" if float(is_use.value) >= floor else "fail",
        value=float(is_use.value),
        engine=is_use.engine,
        threshold=floor,
        decision_row=row,
    )


def _decision_row(run_id: str, is_use: Answer, floor: float) -> Decision:
    return Decision(
        run_id=run_id,
        name=IS_USE_NAME,
        value=is_use.value,
        probability=is_use.probability,
        probabilities=is_use.probabilities,
        engine=is_use.engine,
        latency_ms=is_use.latency_ms,
        reasoning=is_use.reasoning,
        stage=KIND,
        threshold=floor,
    )


def _unavailable_row(run_id: str) -> Decision:
    """The outage's trace row: a 0.0 recorded as `unavailable`, never as a
    reading (KI-57)."""
    return Decision(
        run_id=run_id,
        name=IS_USE_NAME,
        value=0.0,
        probability=0.0,
        probabilities=None,
        engine="unavailable",
        latency_ms=0,
        stage=KIND,
        reasoning=(
            "the decision layer was unreachable for the IsUse check; the "
            "answer was treated as failing and declined with the TR-4 template"
        ),
    )
