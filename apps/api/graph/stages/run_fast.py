"""Fast mode's run stage: rewrite, one retrieval, stream, finish.

Fast reviews after delivery (TR-6): the deltas stream now, and the Reviewer
runs in the shared tail before the terminal event, so the citation chips
recolour while the answer is on screen. It has no delivery plan to choose —
there is nothing to hold.
"""

from __future__ import annotations

import time

from graph.fast import FastRunInput, finalize_fast_run, prepare_fast_run
from graph.generate import build_grounded_messages
from graph.stages.delivery import Delivery
from graph.stages.run_env import FinishRequest, RunEnv
from retrieval.context import count_tokens


async def run_fast(env: RunEnv) -> None:
    run = await prepare_fast_run(
        env.session_factory,
        FastRunInput(
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
    )
    await env.bus.publish(env.run_id, run.retrieval_event)
    env.engine.set_event_emitter(env.emit_decision)

    delivery = Delivery(
        bus=env.bus,
        run_id=env.run_id,
        heartbeat_interval_seconds=env.heartbeat_interval_seconds,
        coalesce_seconds=env.coalesce_seconds,
        on_heartbeat=env.touch_heartbeat,
        mark_first_delta=env.mark_first_delta,
        streamed=True,
        state=env.state,
    )
    started = time.monotonic()
    async for token in run.stream_answer():
        await delivery.push(token)
    await delivery.flush()
    text = env.state.text

    generate_ms = int((time.monotonic() - started) * 1000)
    prompt_tokens = sum(
        count_tokens(message["content"])
        for message in build_grounded_messages(run.rewritten, run.contexts, run.history)
    )
    await finalize_fast_run(
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
            abstained=False,
            plan="stream",
        )
    )
