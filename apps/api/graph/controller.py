"""Controller node (TRD §7 Deep row, §8 catalogue): after each hop, one
Jev Choice decision (argmax) says whether the accumulated notes are
sufficient to answer, or another hop is needed. Stopping past this also
depends on the hop/budget ceiling enforced by the caller (graph/deep.py)."""

import logging

from decisions import DecisionEngine, threshold
from decisions.engine import DecisionUnavailable
from graph.ingress import _pick_choice
from schemas.decisions import Answer, Choice

logger = logging.getLogger(__name__)

CONTROLLER_OPTIONS = ["sufficient", "need_more"]


def _controller_question(question: str, notes: str) -> Choice:
    return Choice(
        prompt=(
            "Do the notes gathered so far contain enough evidence to fully "
            f"answer the question?\n\n[question]\n{question}\n\n[notes]\n{notes}"
        ),
        options=CONTROLLER_OPTIONS,
        criteria="whether every part of the question is answered by the notes",
    )


async def controller_decide(
    engine: DecisionEngine, *, run_id: str, question: str, notes: str
) -> tuple[bool, Answer]:
    """Returns (sufficient, answer) — `sufficient=False` on a low-confidence
    or ambiguous answer too (same safe-default rule as ingress Choices).

    An unreachable decision layer is the same answer: `need_more`, the option
    that spends another hop rather than answering on evidence nobody has read
    (KI-57). Deep is R2b's scope and this is the one line that keeps a decision
    outage from failing a Deep run mid-loop.
    """
    question_asked = _controller_question(question, notes)
    try:
        answers = await engine.decide(
            state={"run_id": run_id, "kind": "controller"},
            questions={"controller": question_asked},
        )
    except DecisionUnavailable as exc:
        logger.warning("decision layer unavailable at the controller (%s)", exc)
        return False, Answer(
            engine="unavailable",
            latency_ms=0,
            value="need_more",
            probability=0.0,
            reasoning=(
                "the decision layer was unreachable; Deep takes another hop "
                "rather than answering without a sufficient reading"
            ),
        )
    answer = answers["controller"]
    choice = _pick_choice(answer, CONTROLLER_OPTIONS, "need_more")
    sufficient = choice == "sufficient" and (
        (answer.probability or 0.0) >= threshold("controller_sufficient", answer.engine)
    )
    return sufficient, answer
