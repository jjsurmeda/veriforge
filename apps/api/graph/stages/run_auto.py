"""Auto mode's run stage: prepare, publish the trace, stream, finish.

Same order as the pipeline it drives — `prepare_auto_run` returns the evidence
and the contexts, this publishes what the trace needs, streams the generator
behind a step of its own, and hands the answer to the shared review tail.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from decisions.thresholds import active_reranker_id, reranker_threshold
from graph.auto import AutoRun, AutoRunInput, finalize_auto_run, prepare_auto_run
from graph.generate import build_grounded_messages
from graph.review import plan_delivery
from graph.stages.delivery import Delivery
from graph.stages.language_check import fix_reply_language
from graph.stages.run_env import FinishRequest, RunEnv
from graph.stages.usefulness_stage import UsefulnessOutcome, run_usefulness, usefulness_decline
from graph.timing import EventPublisher, make_step_timer
from retrieval.context import count_tokens
from schemas.events import AnswerHold, AnswerRetract, Decision, RunStreamEvent

# Small talk has no claims to review, so a "hold" plan would park the reply in
# a branch that only publishes deltas after the review.
_ALWAYS_STREAM = "stream"


async def run_auto(env: RunEnv) -> None:
    env.engine.set_event_emitter(env.emit_decision)
    run = await prepare_auto_run(
        env.session_factory,
        AutoRunInput(
            run_id=env.run_id,
            message_id=env.message_id,
            chat_id=env.chat_id,
            user_id=env.user_id,
            question=env.user_message,
            litellm_model=env.litellm_model,
            small_model=env.small_model,
            context_window=env.context_window,
            source=env.source,
            client_filters=env.client_filters,
            collection_ids=env.collection_ids,
        ),
        env.engine,
        # CH-5: Auto's steps used to be timed but never published, so the trace
        # showed nothing until the run was already over.
        publish=_publish_step(env),
    )
    await _publish_trace(env, run)
    plan = _plan(run)
    if plan == "hold":
        await env.bus.publish(env.run_id, AnswerHold(run_id=str(env.run_id)))

    # The generator gets a step of its own: it is the longest single wait a
    # user sits through, and without a label it was the one stage with nothing
    # on the stream during it. The duration is the SAME measurement as
    # `generate_ms`, read back out of the node metrics rather than timed
    # twice, so the two can never disagree.
    generate_step = make_step_timer(
        node="auto", run_id=env.run_id, latency_ms=run.latency_ms, publish=_publish_step(env)
    )
    delivery = Delivery(
        bus=env.bus,
        run_id=env.run_id,
        heartbeat_interval_seconds=env.heartbeat_interval_seconds,
        coalesce_seconds=env.coalesce_seconds,
        on_heartbeat=env.touch_heartbeat,
        mark_first_delta=env.mark_first_delta,
        streamed=plan == _ALWAYS_STREAM,
        state=env.state,
    )

    async def _generate() -> None:
        async for token in run.stream_answer():
            await delivery.push(token)

    await generate_step("generate", _generate)
    await delivery.flush()
    # Only a grounded answer carries sources to check the answer against; an
    # abstention, a chitchat route or a library listing has none. A held run
    # delivered nothing while generating; a streamed run DID deliver, so its
    # failure is a retraction and publishes `answer.retract` before the tail
    # replaces the text.
    grounded = run.abstain_event is None and not run.chitchat and run.library_names is None
    if grounded and plan == "hold":
        # KI-86: held answers only, so a retry never retracts shown text.
        env.state.text = await fix_reply_language(
            env.user_message,
            env.state.text,
            lambda language: run.seams.stream_grounded_answer(
                litellm_model=run.params.litellm_model,
                question=run.rewritten,
                contexts=run.contexts,
                history=run.history,
                metadata={
                    "run_id": str(run.params.run_id),
                    "user_id": str(run.params.user_id),
                },
                intent=run.ingress.intent,
                language=language,
            ),
        )
    text = env.state.text

    usefulness: UsefulnessOutcome | None = None
    decline_text: str | None = None
    if grounded:
        usefulness_step = make_step_timer(
            node="auto", run_id=env.run_id, latency_ms=run.latency_ms, publish=_publish_step(env)
        )

        async def _run_usefulness() -> None:
            nonlocal usefulness, decline_text
            usefulness = await run_usefulness(
                env.engine,
                run_id=str(env.run_id),
                question=env.user_message,
                answer=env.state.text,
                contexts=run.contexts,
                decisions=run.decision_events,
                on_unavailable=_publish_outage_row(env),
            )
            if usefulness.state != "pass":
                decline_text = await usefulness_decline(
                    str(env.run_id),
                    run.contexts,
                    question=env.user_message,
                    litellm_model=run.params.litellm_model,
                    metadata={"run_id": str(run.params.run_id), "user_id": str(run.params.user_id)},
                )

        await usefulness_step("isuse", _run_usefulness)
    if decline_text is not None and plan == _ALWAYS_STREAM:
        await env.bus.publish(
            env.run_id,
            AnswerRetract(
                run_id=str(env.run_id),
                reason="the usefulness check rejected the answer",
                text=decline_text,
            ),
        )

    generate_ms = run.latency_ms.get("generate", 0)
    prompt_tokens = sum(
        count_tokens(message["content"])
        for message in build_grounded_messages(
            run.rewritten, run.contexts, run.history, run.ingress.intent
        )
    )
    await finalize_auto_run(
        env.session_factory,
        run,
        generate_ms=generate_ms,
        tokens_in=prompt_tokens,
        tokens_out=count_tokens(decline_text or text),
    )
    await env.finish(
        FinishRequest(
            question=run.rewritten,
            text=text,
            contexts=run.contexts,
            latency_ms=run.latency_ms,
            context_used=run.context_used,
            tokens_in=prompt_tokens,
            generate_ms=generate_ms,
            abstained=run.abstain_event is not None,
            plan=plan,
            chitchat=run.chitchat or run.library_names is not None,
            revert_title=run.chitchat,
            decline_text=decline_text,
        )
    )


def _publish_step(env: RunEnv) -> EventPublisher:
    async def publish(run_id: UUID, event: RunStreamEvent) -> None:
        await env.bus.publish(run_id, event)

    return publish


def _publish_outage_row(env: RunEnv) -> Callable[[Decision], Awaitable[None]]:
    """Publish the outage row onto the bus.

    An answered IsUse call's trace row is emitted by the engine's own event
    emitter; a call that never got an answer produced none, and the trace
    still has to say why the answer was declined (KI-57).
    """

    async def publish(row: Decision) -> None:
        await env.bus.publish(env.run_id, row)

    return publish


async def _publish_trace(env: RunEnv, run: AutoRun) -> None:
    for event in run.retrieval_events:
        await env.bus.publish(env.run_id, event)
    if run.conflict_event is not None:
        await env.bus.publish(env.run_id, run.conflict_event)
    if run.abstain_event is not None:
        await env.bus.publish(env.run_id, run.abstain_event)


def _plan(run: AutoRun) -> str:
    if run.abstain_event is not None or run.chitchat or run.library_names is not None:
        return _ALWAYS_STREAM
    # The floor's number and its floor, not the sufficiency reading: the
    # stream decision is about how confidently the run answered, and the
    # rubric grade is what says that (ADR-006 item 4; TRD §10).
    return plan_delivery(
        mode="auto",
        risk=run.ingress.risk,
        evidence_p=run.gate_mean_top3,
        stream_line=reranker_threshold("stream_line", active_reranker_id()),
    )
