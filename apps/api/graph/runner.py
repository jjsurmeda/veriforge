"""Run lifecycle for slice 1: launch, stream, cancel, sweep (TRD §7).

The owning process registers the run's asyncio.Task here; a `run_cancel`
notification from any process routes to _handle_cancel. The 60-s
heartbeat sweep marks orphaned runs failed. Every DB step uses its own
short-lived session (python.md: no ad hoc long-lived sessions in tasks).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from db.models import Message, Run
from errors import AppError
from graph.fast import FastRunInput, finalize_fast_run, prepare_fast_run, to_client_filters
from graph.generate import build_grounded_messages
from retrieval.context import count_tokens
from runbus.postgres import PostgresRunBus
from schemas.chats import RunFilters
from schemas.events import AnswerDelta, Heartbeat, RunCancelled, RunCompleted, RunFailed, RunStarted

logger = logging.getLogger(__name__)

_active_tasks: dict[UUID, asyncio.Task[None]] = {}


def register_with_bus(bus: PostgresRunBus) -> None:
    bus.on_cancel(_handle_cancel)


def _handle_cancel(run_id: UUID) -> None:
    task = _active_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()


class _DeltaBatcher:
    """Coalesces answer text; flushed at least every delta_coalesce_ms (ADR-001)."""

    def __init__(self) -> None:
        self.buffer: list[str] = []
        self.last_flush = time.monotonic()

    def add(self, token: str) -> None:
        self.buffer.append(token)

    def due(self) -> bool:
        return bool(self.buffer) and (
            time.monotonic() - self.last_flush >= get_settings().delta_coalesce_ms / 1000
        )

    def take(self) -> str:
        text = "".join(self.buffer)
        self.buffer.clear()
        self.last_flush = time.monotonic()
        return text


async def _with_session[T](
    session_factory: async_sessionmaker[AsyncSession], work: Callable[[AsyncSession], Awaitable[T]]
) -> T:
    async with session_factory() as session, session.begin():
        return await work(session)


async def _finalize(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    message_id: UUID,
    *,
    status: str,
    text: str,
) -> None:
    async def work(session: AsyncSession) -> None:
        message = await session.get(Message, message_id)
        if message is not None:
            message.content = text
            message.status = status
        await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "running")
            .values(
                status=status if status != "complete" else "completed",
                heartbeat_at=datetime.now(UTC),
                langfuse_trace_id=str(run_id),
            )
        )

    await _with_session(session_factory, work)


async def _touch_heartbeat(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> None:
    async def work(session: AsyncSession) -> None:
        await session.execute(
            update(Run).where(Run.id == run_id).values(heartbeat_at=datetime.now(UTC))
        )

    await _with_session(session_factory, work)


def start_run(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    message_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    litellm_model: str,
    small_litellm_model: str,
    model_id: str,
    context_window: int,
    mode: str,
    source: str,
    user_message: str,
    run_filters: RunFilters | None = None,
    collection_ids: list[UUID] | None = None,
) -> None:
    task = asyncio.create_task(
        execute_run(
            bus=bus,
            session_factory=session_factory,
            run_id=run_id,
            message_id=message_id,
            chat_id=chat_id,
            user_id=user_id,
            litellm_model=litellm_model,
            small_litellm_model=small_litellm_model,
            model_id=model_id,
            context_window=context_window,
            mode=mode,
            source=source,
            user_message=user_message,
            run_filters=run_filters,
            collection_ids=collection_ids or [],
        )
    )
    _active_tasks[run_id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run_id, None))


async def execute_run(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    message_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    litellm_model: str,
    small_litellm_model: str,
    model_id: str,
    context_window: int,
    mode: str,
    source: str,
    user_message: str,
    run_filters: RunFilters | None = None,
    collection_ids: list[UUID] | None = None,
) -> None:
    settings = get_settings()
    text = ""
    try:
        await bus.publish(
            run_id, RunStarted(run_id=str(run_id), mode=mode, source=source, model=model_id)
        )
        await _touch_heartbeat(session_factory, run_id)
        fast_run = await prepare_fast_run(
            session_factory,
            FastRunInput(
                run_id=run_id,
                message_id=message_id,
                chat_id=chat_id,
                user_id=user_id,
                question=user_message,
                litellm_model=litellm_model,
                small_model=small_litellm_model,
                context_window=context_window,
                source=source,
                client_filters=to_client_filters(run_filters),
                collection_ids=collection_ids or [],
            ),
        )
        await bus.publish(run_id, fast_run.retrieval_event)

        batcher = _DeltaBatcher()
        last_heartbeat = time.monotonic()
        generate_start = time.monotonic()

        async for token in fast_run.stream_answer():
            text += token
            batcher.add(token)
            if batcher.due():
                await bus.publish(
                    run_id, AnswerDelta(run_id=str(run_id), text=batcher.take())
                )
                if time.monotonic() - last_heartbeat >= settings.heartbeat_interval_seconds:
                    await bus.publish(run_id, Heartbeat(run_id=str(run_id)))
                    await _touch_heartbeat(session_factory, run_id)
                    last_heartbeat = time.monotonic()
        if batcher.buffer:
            await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))

        generate_ms = int((time.monotonic() - generate_start) * 1000)
        prompt_tokens = sum(
            count_tokens(m["content"])
            for m in build_grounded_messages(
                fast_run.rewritten, fast_run.contexts, fast_run.history
            )
        )
        metrics_event = await finalize_fast_run(
            session_factory,
            fast_run,
            generate_ms=generate_ms,
            tokens_in=prompt_tokens,
            tokens_out=count_tokens(text),
        )
        await bus.publish(run_id, metrics_event)
        await _finalize(session_factory, run_id, message_id, status="complete", text=text)
        await bus.publish(run_id, RunCompleted(run_id=str(run_id), message_id=str(message_id)))

    except asyncio.CancelledError:
        await _finalize(session_factory, run_id, message_id, status="cancelled", text=text)
        try:
            await bus.publish(
                run_id, RunCancelled(run_id=str(run_id), message_id=str(message_id))
            )
        finally:
            raise

    except AppError as exc:
        logger.error(
            "run failed", extra={"run_id": str(run_id), "error_code": exc.error_code}
        )
        await _finalize(session_factory, run_id, message_id, status="failed", text=text)
        await bus.publish(
            run_id,
            RunFailed(
                run_id=str(run_id), error_code=exc.error_code, message=exc.message
            ),
        )

    except Exception:
        logger.exception("run failed", extra={"run_id": str(run_id)})
        await _finalize(session_factory, run_id, message_id, status="failed", text=text)
        await bus.publish(
            run_id,
            RunFailed(
                run_id=str(run_id),
                error_code="run_error",
                message="The run failed before completing",
            ),
        )


async def sweep_stale_runs(
    bus: PostgresRunBus, session_factory: async_sessionmaker[AsyncSession]
) -> int:
    """Mark runs in `running` with no heartbeat for 60 s failed (TRD §7)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=get_settings().heartbeat_sweep_seconds)

    async def work(session: AsyncSession) -> list[tuple[UUID, UUID]]:
        stale = (
            await session.execute(
                select(Run.id, Run.message_id).where(
                    Run.status == "running",
                    Run.heartbeat_at.is_not(None),
                    Run.heartbeat_at < cutoff,
                )
            )
        ).all()
        for run_id, message_id in stale:
            message = await session.get(Message, message_id)
            if message is not None and message.status is None:
                message.status = "failed"
            await session.execute(update(Run).where(Run.id == run_id).values(status="failed"))
        return [(r[0], r[1]) for r in stale]

    stale = await _with_session(session_factory, work)
    for run_id, _message_id in stale:
        await bus.publish(
            run_id,
            RunFailed(
                run_id=str(run_id),
                error_code="heartbeat_timeout",
                message="Run lost its worker and was marked failed",
            ),
        )
    return len(stale)


async def sweep_loop(
    bus: PostgresRunBus, session_factory: async_sessionmaker[AsyncSession], interval: float = 15.0
) -> None:
    while True:
        try:
            await sweep_stale_runs(bus, session_factory)
        except Exception:
            logger.exception("heartbeat sweep failed")
        await asyncio.sleep(interval)
