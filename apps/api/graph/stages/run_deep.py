"""Deep mode's run stage: plan, hop, stream the answer and its reasoning,
finish.

Deep always holds the answer until the review is done, except when it
abstained: there is nothing to review in a fixed-template decline, so it
streams.
"""

from __future__ import annotations

import time
from uuid import UUID

from graph.deep import DeepRunInput, finalize_deep_run, prepare_deep_run
from graph.generate import build_grounded_messages
from graph.stages.delivery import Delivery
from graph.stages.run_env import FinishRequest, RunEnv
from graph.timing import EventPublisher
from retrieval.context import count_tokens
from schemas.events import AnswerHold, RunStreamEvent, ThinkingDelta


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
    started = time.monotonic()
    async for kind, token in run.stream_answer_with_thinking():
        if kind == "thinking":
            await env.bus.publish(
                env.run_id, ThinkingDelta(run_id=str(env.run_id), text=token)
            )
            continue
        await delivery.push(token)
    await delivery.flush()
    text = env.state.text

    generate_ms = int((time.monotonic() - started) * 1000)
    prompt_tokens = sum(
        count_tokens(message["content"])
        for message in build_grounded_messages(run.rewritten, run.contexts, run.history)
    )
    await finalize_deep_run(
        env.session_factory,
        run,
        generate_ms=generate_ms,
        tokens_in=prompt_tokens,
        tokens_out=count_tokens(text),
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
        )
    )


def _publish_step(env: RunEnv) -> EventPublisher:
    async def publish(run_id: UUID, event: RunStreamEvent) -> None:
        await env.bus.publish(run_id, event)

    return publish
