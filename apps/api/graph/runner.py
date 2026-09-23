"""Run lifecycle for slice 1: launch, stream, cancel, sweep (TRD §7).

The owning process registers the run's asyncio.Task here; a `run_cancel`
notification from any process routes to _handle_cancel. The 60-s
heartbeat sweep marks orphaned runs failed. Every DB step uses its own
short-lived session (python.md: no ad hoc long-lived sessions in tasks).

Slice 4 dispatches on mode: fast (slice 3) → graph/fast.py; auto →
graph/auto.py; deep → graph/deep.py (slice 5: real Plan/Hop/Controller
path, replacing slice 4's auto-with-a-notice fallback). Slice 6 adds
risk-based delivery (TR-6) and the shared review tail (_finish_answer):
claim verification, single revision pass, output guardrail, suggestions,
runs.metrics and fire-and-forget async scoring.
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from db.models import Citation, Claim, Message, Run
from decisions import DecisionEngine, make_shadow_writer
from decisions.output_guard import OutputGuardResult, guard_output
from decisions.thresholds import threshold
from errors import AppError
from graph.async_scoring import score_run_async
from graph.auto import AutoRunInput, finalize_auto_run, prepare_auto_run
from graph.deep import DeepRunInput, finalize_deep_run, prepare_deep_run
from graph.fast import FastRunInput, finalize_fast_run, prepare_fast_run, to_client_filters
from graph.generate import build_grounded_messages
from graph.review import (
    ReviewResult,
    plan_delivery,
    review_answer,
)
from graph.suggestions import generate_suggestions
from retrieval.context import count_tokens
from retrieval.expand import ExpandedContext
from runbus.postgres import PostgresRunBus
from schemas.chats import RunFilters
from schemas.decisions import Answer
from schemas.events import (
    AnswerDelta,
    AnswerHold,
    Decision,
    Heartbeat,
    Metrics,
    ReviewClaim,
    Revision,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunStarted,
    RunStreamEvent,
    Suggestions,
    ThinkingDelta,
)

logger = logging.getLogger(__name__)

_REVIEW_REFUSAL = (
    "This response was blocked by Veriforge's output guard before it "
    "could be delivered. Please rephrase your request."
)

_active_tasks: dict[UUID, asyncio.Task[None]] = {}

_decision_engine: DecisionEngine | None = None


def get_decision_engine(session_factory: async_sessionmaker[AsyncSession]) -> DecisionEngine:
    """Process-local engine, built on first use so tests can monkeypatch."""
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = DecisionEngine(shadow_writer=make_shadow_writer(session_factory))
    return _decision_engine


def reset_decision_engine() -> None:
    """Test hook: drop the cached engine between tests."""
    global _decision_engine
    _decision_engine = None


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
    metrics: dict[str, object] | None = None,
) -> None:
    async def work(session: AsyncSession) -> None:
        message = await session.get(Message, message_id)
        if message is not None:
            message.content = text
            message.status = status
        values: dict[str, object] = {
            "heartbeat_at": datetime.now(UTC),
            "langfuse_trace_id": str(run_id),
        }
        if metrics is not None:
            values["metrics"] = metrics
        # runs.status enum has no "abstained" — that's a message status.
        run_status = "completed" if status in ("complete", "abstained") else status
        await session.execute(
            update(Run).where(Run.id == run_id, Run.status == "running").values(
                status=run_status, **values
            )
        )

    await _with_session(session_factory, work)


async def _touch_heartbeat(session_factory: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    async def work(session: AsyncSession) -> None:
        await session.execute(
            update(Run).where(Run.id == run_id).values(heartbeat_at=datetime.now(UTC))
        )

    await _with_session(session_factory, work)


async def _persist_review(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: UUID,
    review: ReviewResult | None,
) -> None:
    """Write claims rows and aggregate verdicts onto citations
    (citations.verdict/p_supported sat nullable since slice 3)."""

    async def work(session: AsyncSession) -> None:
        if review is None:
            return
        for vc in review.claims:
            session.add(
                Claim(
                    message_id=message_id,
                    text=vc.claim.text,
                    citation_ns=vc.claim.citation_ids,
                    is_factual=vc.claim.is_factual,
                    verdict=vc.verdict if vc.claim.is_factual else None,
                    p_supported=vc.p_supported if vc.claim.is_factual else None,
                    engine=vc.engine if vc.claim.is_factual else None,
                )
            )
        per_citation: dict[int, list[str]] = {}
        p_by_citation: dict[int, list[float]] = {}
        for vc in review.claims:
            if not vc.claim.is_factual:
                continue
            for n in vc.claim.citation_ids:
                per_citation.setdefault(n, []).append(vc.verdict)
                p_by_citation.setdefault(n, []).append(vc.p_supported)
        if not per_citation:
            return
        citations = (
            (await session.execute(select(Citation).where(Citation.message_id == message_id)))
            .scalars()
            .all()
        )
        for citation in citations:
            verdicts = per_citation.get(citation.n)
            if not verdicts:
                continue
            if "contradicted" in verdicts:
                citation.verdict = "contradicted"
            elif "unsupported" in verdicts:
                citation.verdict = "unsupported"
            elif "partial" in verdicts:
                citation.verdict = "partial"
            else:
                citation.verdict = "supported"
            citation.p_supported = min(p_by_citation[citation.n])

    await _with_session(session_factory, work)


async def _compute_review(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    engine: DecisionEngine,
    run_id: UUID,
    message_id: UUID,
    question: str,
    answer: str,
    contexts: list[ExpandedContext],
    latency_ms: dict[str, int],
    litellm_model: str,
    small_model: str,
) -> tuple[str, ReviewResult | None, list[str], OutputGuardResult | None]:
    """Review + suggestions in parallel, then the guard on the final
    (possibly revised) text. Persists claims/citation verdicts. Returns
    (final_text, review, suggestions, guard) — events are published by the
    caller so hold paths can land the answer first."""
    started = time.monotonic()
    cited_ns = sorted({int(m) for m in re.findall(r"\[(\d{1,2})\]", answer)})
    review_task = asyncio.create_task(
        review_answer(
            engine=engine,
            run_id=str(run_id),
            answer=answer,
            contexts=contexts,
            citation_count=len(contexts),
            small_model=small_model,
            litellm_model=litellm_model,
        )
    )
    suggestions_task = asyncio.create_task(
        generate_suggestions(
            question=question,
            answer=answer,
            contexts=contexts,
            cited_ns=cited_ns,
            small_model=small_model,
        )
    )
    review_result, suggestions = await asyncio.gather(review_task, suggestions_task)
    latency_ms["review"] = int((time.monotonic() - started) * 1000)

    final_text = answer
    if review_result is not None and review_result.revised_text is not None:
        final_text = review_result.revised_text
    guard = await guard_output(engine, run_id=str(run_id), text=final_text)
    if guard.blocked:
        final_text = _REVIEW_REFUSAL

    await _persist_review(session_factory, message_id=message_id, review=review_result)
    return final_text, review_result, suggestions, guard


async def _publish_review(
    bus: PostgresRunBus,
    run_id: UUID,
    *,
    review: ReviewResult | None,
    suggestions: list[str],
    blocked: bool,
) -> None:
    if blocked:
        return
    if review is not None:
        for vc in review.claims:
            if not vc.claim.is_factual:
                continue
            await bus.publish(
                run_id,
                ReviewClaim(
                    run_id=str(run_id),
                    claim_id=vc.claim.claim_id,
                    text=vc.claim.text,
                    citation_ids=[str(n) for n in vc.claim.citation_ids],
                    verdict=vc.verdict,
                    p_supported=vc.p_supported,
                ),
            )
        if review.revised_text is not None:
            await bus.publish(
                run_id,
                Revision(
                    run_id=str(run_id),
                    revised_text=review.revised_text,
                    diff=review.diff or "",
                ),
            )
    if suggestions:
        await bus.publish(run_id, Suggestions(run_id=str(run_id), questions=suggestions))


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


async def _finish_answer(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    engine: DecisionEngine,
    run_id: UUID,
    message_id: UUID,
    question: str,
    text: str,
    contexts: list[ExpandedContext],
    latency_ms: dict[str, int],
    context_used: int,
    context_window: int,
    litellm_model: str,
    small_model: str,
    tokens_in: int,
    generate_ms: int,
    extra_credits: int,
    abstained: bool,
    plan: str,
) -> None:
    """Shared tail for every mode: review phase (skipped for abstentions —
    the fixed template has no claims to verify), event order per delivery
    plan, runs.metrics persistence, fire-and-forget async scoring."""
    final_text = text
    review: ReviewResult | None = None
    suggestions: list[str] = []
    guard: OutputGuardResult | None = None
    blocked = False
    if not abstained:
        final_text, review, suggestions, guard = await _compute_review(
            bus=bus,
            session_factory=session_factory,
            engine=engine,
            run_id=run_id,
            message_id=message_id,
            question=question,
            answer=text,
            contexts=contexts,
            latency_ms=latency_ms,
            litellm_model=litellm_model,
            small_model=small_model,
        )
        blocked = guard is not None and guard.blocked
        if plan == "hold":
            await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=final_text))
        await _publish_review(bus, run_id, review=review, suggestions=suggestions, blocked=blocked)
        # plan == "stream" + blocked: the answer already streamed; the
        # blocked verdict replaces the persisted content, which is what a
        # reload shows (TRD §11 "output toxicity (block)").

    tokens_out = count_tokens(final_text)
    latency = {**latency_ms, "generate": generate_ms}
    scores = review.scores if review is not None else None
    credits = extra_credits + tokens_in + tokens_out
    await bus.publish(
        run_id,
        Metrics(
            run_id=str(run_id),
            latency_ms=latency,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            credits=credits,
            context_used=context_used,
            context_window=context_window,
            faithfulness=scores.faithfulness if scores else None,
            min_support=scores.min_support if scores else None,
        ),
    )
    metrics: dict[str, object] = {
        "latency_ms": latency,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "credits": credits,
        "context_used": context_used,
        "context_window": context_window,
        "faithfulness": scores.faithfulness if scores else None,
        "min_support": scores.min_support if scores else None,
        "revised": review is not None and review.revised_text is not None,
        "revision_diff": review.diff if review is not None else None,
        "suggestions": suggestions,
    }
    status = "abstained" if abstained else "complete"
    await _finalize(
        session_factory, run_id, message_id, status=status, text=final_text, metrics=metrics
    )
    if not abstained:
        asyncio.get_running_loop().create_task(
            score_run_async(run_id=run_id, question=question, answer=final_text, contexts=contexts)
        )
    await bus.publish(
        run_id,
        RunCompleted(
            run_id=str(run_id),
            message_id=str(message_id),
            status="abstained" if abstained else "completed",
        ),
    )


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

        async def emit_decision(name: str, answer: Answer) -> None:
            await bus.publish(
                run_id,
                Decision(
                    run_id=str(run_id),
                    name=name,
                    value=answer.value,
                    probability=answer.probability,
                    probabilities=answer.probabilities,
                    engine=answer.engine,
                    latency_ms=answer.latency_ms,
                    reasoning=answer.reasoning,
                ),
            )

        if mode == "auto":
            engine = get_decision_engine(session_factory)
            engine.set_event_emitter(emit_decision)
            auto_run = await prepare_auto_run(
                session_factory,
                AutoRunInput(
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
                engine,
            )
            for event in auto_run.retrieval_events:
                await bus.publish(run_id, event)
            if auto_run.conflict_event is not None:
                await bus.publish(run_id, auto_run.conflict_event)
            if auto_run.abstain_event is not None:
                await bus.publish(run_id, auto_run.abstain_event)

            plan = (
                "stream"
                if auto_run.abstain_event is not None
                else plan_delivery(
                    mode="auto",
                    risk=auto_run.ingress.risk,
                    sufficiency_p=auto_run.sufficiency_p,
                    sufficient_threshold=threshold("sufficient_retry", "jev"),
                )
            )
            if plan == "hold":
                await bus.publish(run_id, AnswerHold(run_id=str(run_id)))

            batcher = _DeltaBatcher()
            last_heartbeat = time.monotonic()
            generate_start = time.monotonic()

            async for token in auto_run.stream_answer():
                text += token
                batcher.add(token)
                if plan == "stream" and batcher.due():
                    await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))
                    if time.monotonic() - last_heartbeat >= settings.heartbeat_interval_seconds:
                        await bus.publish(run_id, Heartbeat(run_id=str(run_id)))
                        await _touch_heartbeat(session_factory, run_id)
                        last_heartbeat = time.monotonic()
            if plan == "stream" and batcher.buffer:
                await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))

            generate_ms = int((time.monotonic() - generate_start) * 1000)
            prompt_tokens = sum(
                count_tokens(m["content"])
                for m in build_grounded_messages(
                    auto_run.rewritten, auto_run.contexts, auto_run.history
                )
            )
            await finalize_auto_run(
                session_factory,
                auto_run,
                generate_ms=generate_ms,
                tokens_in=prompt_tokens,
                tokens_out=count_tokens(text),
            )
            await _finish_answer(
                bus=bus,
                session_factory=session_factory,
                engine=engine,
                run_id=run_id,
                message_id=message_id,
                question=auto_run.rewritten,
                text=text,
                contexts=auto_run.contexts,
                latency_ms=auto_run.latency_ms,
                context_used=auto_run.context_used,
                context_window=context_window,
                litellm_model=litellm_model,
                small_model=small_litellm_model,
                tokens_in=prompt_tokens,
                generate_ms=generate_ms,
                extra_credits=0,
                abstained=auto_run.abstain_event is not None,
                plan=plan,
            )
            return

        if mode == "deep":
            engine = get_decision_engine(session_factory)
            engine.set_event_emitter(emit_decision)

            async def _publish_step(rid: UUID, event: RunStreamEvent) -> None:
                await bus.publish(rid, event)

            deep_run = await prepare_deep_run(
                session_factory,
                DeepRunInput(
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
                engine,
                publish=_publish_step,
            )
            await bus.publish(run_id, deep_run.plan_event)
            for event in deep_run.retrieval_events:
                await bus.publish(run_id, event)
            if deep_run.abstain_event is not None:
                await bus.publish(run_id, deep_run.abstain_event)

            plan = "stream" if deep_run.abstain_event is not None else "hold"
            if plan == "hold":
                await bus.publish(run_id, AnswerHold(run_id=str(run_id)))

            batcher = _DeltaBatcher()
            last_heartbeat = time.monotonic()
            generate_start = time.monotonic()

            async for kind, token in deep_run.stream_answer_with_thinking():
                if kind == "thinking":
                    await bus.publish(run_id, ThinkingDelta(run_id=str(run_id), text=token))
                    continue
                text += token
                batcher.add(token)
                if plan == "stream" and batcher.due():
                    await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))
                    if time.monotonic() - last_heartbeat >= settings.heartbeat_interval_seconds:
                        await bus.publish(run_id, Heartbeat(run_id=str(run_id)))
                        await _touch_heartbeat(session_factory, run_id)
                        last_heartbeat = time.monotonic()
            if plan == "stream" and batcher.buffer:
                await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))

            generate_ms = int((time.monotonic() - generate_start) * 1000)
            prompt_tokens = sum(
                count_tokens(m["content"])
                for m in build_grounded_messages(
                    deep_run.rewritten, deep_run.contexts, deep_run.history
                )
            )
            await finalize_deep_run(
                session_factory,
                deep_run,
                generate_ms=generate_ms,
                tokens_in=prompt_tokens,
                tokens_out=count_tokens(text),
            )
            await _finish_answer(
                bus=bus,
                session_factory=session_factory,
                engine=engine,
                run_id=run_id,
                message_id=message_id,
                question=deep_run.rewritten,
                text=text,
                contexts=deep_run.contexts,
                latency_ms=deep_run.latency_ms,
                context_used=deep_run.context_used,
                context_window=context_window,
                litellm_model=litellm_model,
                small_model=small_litellm_model,
                tokens_in=prompt_tokens,
                generate_ms=generate_ms,
                extra_credits=deep_run.credits_used,
                abstained=deep_run.abstain_event is not None,
                plan=plan,
            )
            return

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

        # Fast reviews async after delivery (TR-6): deltas stream now, the
        # Reviewer runs in _finish_answer before the terminal event so chips
        # recolour while the answer is on screen.
        engine = get_decision_engine(session_factory)
        engine.set_event_emitter(emit_decision)

        batcher = _DeltaBatcher()
        last_heartbeat = time.monotonic()
        generate_start = time.monotonic()

        async for token in fast_run.stream_answer():
            text += token
            batcher.add(token)
            if batcher.due():
                await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=batcher.take()))
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
        await finalize_fast_run(
            session_factory,
            fast_run,
            generate_ms=generate_ms,
            tokens_in=prompt_tokens,
            tokens_out=count_tokens(text),
        )
        await _finish_answer(
            bus=bus,
            session_factory=session_factory,
            engine=engine,
            run_id=run_id,
            message_id=message_id,
            question=fast_run.rewritten,
            text=text,
            contexts=fast_run.contexts,
            latency_ms=fast_run.latency_ms,
            context_used=fast_run.context_used,
            context_window=context_window,
            litellm_model=litellm_model,
            small_model=small_litellm_model,
            tokens_in=prompt_tokens,
            generate_ms=generate_ms,
            extra_credits=0,
            abstained=False,
            plan="stream",
        )

    except asyncio.CancelledError:
        await _finalize(session_factory, run_id, message_id, status="cancelled", text=text)
        try:
            await bus.publish(run_id, RunCancelled(run_id=str(run_id), message_id=str(message_id)))
        finally:
            raise

    except AppError as exc:
        logger.error("run failed", extra={"run_id": str(run_id), "error_code": exc.error_code})
        await _finalize(session_factory, run_id, message_id, status="failed", text=text)
        await bus.publish(
            run_id,
            RunFailed(run_id=str(run_id), error_code=exc.error_code, message=exc.message),
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
