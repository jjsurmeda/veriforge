"""Deep mode's run stage: plan, hop, stream the answer and its reasoning,
finish.

Deep always holds the answer until the review is done, except when it
abstained: there is nothing to review in a fixed-template decline, so it
streams.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from graph.deep import DeepRunInput, finalize_deep_run, prepare_deep_run
from graph.generate import build_grounded_messages, stream_grounded_answer
from graph.stages.delivery import Delivery
from graph.stages.language_check import fix_reply_language
from graph.stages.run_env import FinishRequest, RunEnv
from graph.stages.usefulness_stage import UsefulnessOutcome, run_usefulness, usefulness_decline
from graph.timing import EventPublisher, make_step_timer
from retrieval.context import count_tokens
from schemas.events import AnswerHold, Decision, RunStreamEvent, ThinkingDelta


async def run_deep(env: RunEnv) -> None:
    env.engine.set_event_emitter(env.emit_decision)
    run = await prepare_deep_run(
        env.session_factory,
        DeepRunInput(
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
        publish=_publish_step(env),
    )
    await env.bus.publish(env.run_id, run.plan_event)
    for event in run.retrieval_events:
        await env.bus.publish(env.run_id, event)
    # Deep's computed evidence-gate row (R2b item 1): no engine call produced
    # it, so without this the trace never shows what graded the evidence. This
    # is new on the bus for Deep; Auto keeps its gate row in decision_events
    # only.
    if run.gate_event is not None:
        await env.bus.publish(env.run_id, run.gate_event)
    for row in run.entity_unavailable_rows:
        await env.bus.publish(env.run_id, row)
    if run.conflict_event is not None:
        await env.bus.publish(env.run_id, run.conflict_event)
    if run.abstain_event is not None:
        await env.bus.publish(env.run_id, run.abstain_event)

    plan = "stream" if run.abstain_event is not None else "hold"
    if plan == "hold":
        await env.bus.publish(env.run_id, AnswerHold(run_id=str(env.run_id)))

    delivery = Delivery(
        bus=env.bus,
        run_id=env.run_id,
        heartbeat_interval_seconds=env.heartbeat_interval_seconds,
        coalesce_seconds=env.coalesce_seconds,
        on_heartbeat=env.touch_heartbeat,
        mark_first_delta=env.mark_first_delta,
        streamed=plan == "stream",
        state=env.state,
    )
    generate_step = make_step_timer(
        node="deep", run_id=env.run_id, latency_ms=run.latency_ms, publish=_publish_step(env)
    )

    async def _generate() -> None:
        async for kind, token in run.stream_answer_with_thinking():
            if kind == "thinking":
                await env.bus.publish(
                    env.run_id, ThinkingDelta(run_id=str(env.run_id), text=token)
                )
                continue
            await delivery.push(token)
        await delivery.flush()

    await generate_step("generate", _generate)
    if plan == "hold":  # KI-86: Deep holds every grounded answer
        env.state.text = await fix_reply_language(
            env.user_message,
            env.state.text,
            lambda language: stream_grounded_answer(
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

    # IsUse (ADR-006, R2b item 1): the same post-generation check Auto runs,
    # on the grounded answer and its sources. Deep's answers are held, so a
    # failure needs no retraction — the decline goes into `decline_text` and
    # the held plan publishes it when the review releases the reply. A held
    # outage (KI-57, fail-closed) reads to the tail exactly like a failing
    # check and still ends `completed`.
    usefulness: UsefulnessOutcome | None = None
    decline_text: str | None = None
    grounded = run.abstain_event is None
    if grounded:
        usefulness_step = make_step_timer(
            node="deep", run_id=env.run_id, latency_ms=run.latency_ms, publish=_publish_step(env)
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

    generate_ms = run.latency_ms.get("generate", 0)
    prompt_tokens = sum(
        count_tokens(message["content"])
        for message in build_grounded_messages(
            run.rewritten, run.contexts, run.history, run.ingress.intent
        )
    )
    await finalize_deep_run(
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
            decline_text=decline_text,
            finish_reason=run.generation_finish_reason,
        )
    )


def _publish_step(env: RunEnv) -> EventPublisher:
    async def publish(run_id: UUID, event: RunStreamEvent) -> None:
        await env.bus.publish(run_id, event)

    return publish


def _publish_outage_row(env: RunEnv) -> Callable[[Decision], Awaitable[None]]:
    """Publish the IsUse outage row onto the bus (KI-57) — the same tail
    Auto's stage uses."""

    async def publish(row: Decision) -> None:
        await env.bus.publish(env.run_id, row)

    return publish
