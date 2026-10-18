"""Finish stage: the evidence verdict becomes the run's answer.

An abstention carries no contexts and persists no citations; what was found
reaches the user as plain text in the abstain message. An answering run gets
its conflict event, its trimmed contexts and its citation rows.
"""

from __future__ import annotations

from functools import partial
from itertools import combinations

from db.models import Citation
from decisions import threshold
from graph.abstain import build_abstain_event
from graph.generate import order_for_lost_in_the_middle
from graph.stages.checks import _conflict_pair_questions
from graph.stages.common import no_call
from graph.stages.evidence_stage import Attempt
from graph.stages.ingress_stage import direct_run
from graph.stages.retrieve_stage import SUMMARY_SOURCE_TYPE
from graph.stages.state import AutoRun, AutoRunState, StageEnv
from retrieval.context import count_tokens, trim_context
from retrieval.hybrid import ScoredChunk
from runtime import runtime_value
from schemas.decisions import Answer
from schemas.events import Conflict


async def finish(env: StageEnv, state: AutoRunState, attempt: Attempt) -> AutoRun:
    """The last attempt's verdict, the contexts or the abstention, and the
    citation rows the generator will answer from."""
    _mark_dropped(state)
    # The gate's own number. `plan_delivery` reads it to decide hold-vs-stream,
    # and a run must be held or streamed on the signal that decided whether it
    # answered at all.
    state.gate_mean_top3 = attempt.gate_mean_top3
    if attempt.enough:
        await _resolve_conflict(env, state, attempt)
        state.contexts = attempt.expanded
    elif state.chitchat_route:
        # The run retrieved, the evidence did not support an answer, so it says
        # so in its own words rather than by asserting something about the
        # sources. The decision and retrieval events are dropped with the
        # contexts: this reply cites nothing.
        return direct_run(env, state, env.params.question, chitchat=True, keep_decisions=False)
    else:
        state.abstain_event = build_abstain_event(
            str(env.params.run_id), attempt.winners, offered_actions=["web", "deep"]
        )
    _trim(env, state)
    _cite(env, state)
    return AutoRun(
        params=env.params,
        history=state.history,
        contexts=state.contexts,
        kept_chunks=attempt.winners,
        dropped_chunks=state.dropped_chunks,
        rewritten=state.rewritten,
        retrieval_events=state.retrieval_events,
        decision_events=state.decision_events,
        conflict_event=state.conflict_event,
        abstain_event=state.abstain_event,
        latency_ms=env.latency_ms,
        context_used=state.context_used,
        ingress=state.ingress,
        seams=env.seams,
        gate_mean_top3=state.gate_mean_top3,
        retry_skipped=state.retry_skipped,
    )


def _mark_dropped(state: AutoRunState) -> None:
    """Flag every dropped chunk on the retrieval events the client already
    saw, so the trace shows which candidates were kept."""
    dropped_ids = {str(chunk.chunk_id) for chunk in state.dropped_chunks}
    for event in state.retrieval_events:
        for chunk in event.chunks:
            if chunk.chunk_id in dropped_ids:
                chunk.dropped = True


async def _resolve_conflict(env: StageEnv, state: AutoRunState, attempt: Attempt) -> None:
    """The pair that fires names the two passages, and those two are the sides
    the event shows.

    On the common path the pairs already rode the post-sanitize call, so this
    stage is the same `conflict` step timed at its true cost — assembling the
    event rather than a second round trip. When the sanitizer dropped
    something the pairs were not batched, and they are asked here, over the
    kept set.
    """
    if attempt.batched_pairs:
        answers = attempt.batched_conflict_answers
        await env.step("conflict", no_call)
    elif len(attempt.sides) >= 2:
        answers = await env.step(
            "conflict",
            partial(
                env.engine.decide,
                state={"run_id": str(env.params.run_id), "kind": "conflict"},
                questions=_conflict_pair_questions(attempt.sides, env.params.question),
            ),
        )
    else:
        return
    conflict = _best_conflict(env, attempt, answers)
    if conflict is not None:
        state.conflict_event = conflict


def _best_conflict(
    env: StageEnv, attempt: Attempt, answers: dict[str, Answer]
) -> Conflict | None:
    best: tuple[ScoredChunk, ScoredChunk, Answer] | None = None
    for index, (left, right) in enumerate(combinations(attempt.sides, 2)):
        pair_answer = answers.get(f"conflict_{index}")
        if pair_answer is None:
            continue
        if float(pair_answer.value) > 0 and (
            best is None or float(pair_answer.value) > float(best[2].value)
        ):
            best = (left, right, pair_answer)
    if best is None or float(best[2].value) < threshold("conflict_disclose", best[2].engine):
        return None
    left, right, _ = best
    return Conflict(
        run_id=str(env.params.run_id),
        citation_ids_left=[str(left.chunk_id)],
        citation_ids_right=[str(right.chunk_id)],
        rule_applied=str(runtime_value("source_priority", "documents_first")),
    )


def _trim(env: StageEnv, state: AutoRunState) -> None:
    history_tokens = sum(count_tokens(text) for _, text in state.history[-6:])
    trimmed, state.context_used = trim_context(
        state.contexts,
        window_tokens=env.params.context_window,
        history_tokens=history_tokens,
    )
    state.contexts = order_for_lost_in_the_middle(trimmed)


def _cite(env: StageEnv, state: AutoRunState) -> None:
    env.session.add_all(
        Citation(
            message_id=env.params.message_id,
            n=index + 1,
            # Summaries carry a synthetic chunk_id that matches no row in
            # `chunks`; the foreign key is nullable so a summary citation
            # points through document_id/section_id instead (_merge_summaries).
            chunk_id=context.chunk.chunk_id
            if context.chunk.source_type != SUMMARY_SOURCE_TYPE
            else None,
            rerank_score=context.chunk.rerank_score,
        )
        for index, context in enumerate(state.contexts)
    )

