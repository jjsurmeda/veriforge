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

`collection_ids` on every entry point below is the *resolved scope* for the
run — the router calls chats.scope.resolve_scope once and passes the result
down, so nothing in here re-derives or re-validates it (ADR-002).
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from contextvars import Token
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from db.models import Citation, Claim, LlmProvider, Message, Model, ModelRole, Run
from decisions import DecisionCall, DecisionEngine, display_threshold, make_shadow_writer
from decisions.output_guard import OutputGuardResult, guard_output
from decisions.thresholds import threshold
from errors import AppError
from graph.async_scoring import score_run_async
from graph.chat_title import refine_chat_title
from graph.fast import to_client_filters
from graph.review import (
    ReviewResult,
    review_answer,
)
from graph.stages.run_auto import run_auto
from graph.stages.run_deep import run_deep
from graph.stages.run_env import FinishRequest, RunEnv, RunState
from graph.stages.run_fast import run_fast
from graph.suggestions import generate_suggestions
from observability import signals
from providers.credentials import decrypt_provider_key
from providers.llm import classify_provider_error
from quota.service import settle_run
from quota.usage import UsageContext, get_usage_context, reset_usage_context, set_usage_context
from retrieval.context import count_tokens
from retrieval.expand import ExpandedContext
from runbus.postgres import PostgresRunBus
from runtime import (
    RuntimeSettings,
    load_runtime_version,
    reset_runtime_settings,
    set_runtime_settings,
)
from schemas.chats import RunFilters
from schemas.decisions import Answer, Noul
from schemas.events import (
    AnswerDelta,
    Decision,
    Heartbeat,
    Metrics,
    ReviewClaim,
    Revision,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunStarted,
    Suggestions,
)

logger = logging.getLogger(__name__)

_REVIEW_REFUSAL = (
    "This response was blocked by Veriforge's output guard before it "
    "could be delivered. Please rephrase your request."
)

_active_tasks: dict[UUID, asyncio.Task[None]] = {}
# Per-run work that outlives the response on purpose (async judge, then the
# usage settle). Nothing awaits it, so it has to be tracked to be drainable at
# shutdown and between tests — otherwise the settle is lost and the ledger row
# stays `reserved`.
_background_tasks: set[asyncio.Task[None]] = set()


def _track_background(task: asyncio.Task[None]) -> asyncio.Task[None]:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def drain_background_tasks() -> None:
    """Await every tracked per-run tail. Loops because a drained task can
    register another one before it returns."""
    while _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)


async def _runtime_context(
    session_factory: async_sessionmaker[AsyncSession], settings_version: int | None
) -> tuple[RuntimeSettings, dict[str, str], dict[str, str]]:
    async with session_factory() as session:
        runtime = await load_runtime_version(session, settings_version)
        rows = (
            await session.execute(
                select(
                    ModelRole.role,
                    ModelRole.model_id,
                    LlmProvider.kind,
                    LlmProvider.api_key_enc,
                )
                .join(Model, Model.model_id == ModelRole.model_id)
                .join(LlmProvider, LlmProvider.id == Model.provider_id)
                .where(Model.enabled, LlmProvider.enabled)
            )
        ).all()
    roles = {role: f"{kind}/{model_id}" for role, model_id, kind, _key in rows}
    api_keys = {
        f"{kind}/{model_id}": decrypt_provider_key(key)
        for _role, model_id, kind, key in rows
        if key
    }
    if "rewriter" not in roles and "small" in roles:
        roles["rewriter"] = roles["small"]
    return runtime, roles, api_keys


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
    settle_usage: bool = True,
) -> None:
    async def work(session: AsyncSession) -> None:
        if settle_usage:
            context = get_usage_context()
            snapshot = context.snapshot() if context is not None else None
            await settle_run(session, run_id, snapshot)
        message = await session.get(Message, message_id)
        if message is not None:
            if status != "cancelled" or text:
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
            update(Run)
            .where(Run.id == run_id, Run.status == "running")
            .values(status=run_status, **values)
        )

    await _with_session(session_factory, work)


async def _touch_heartbeat(session_factory: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    async def work(session: AsyncSession) -> None:
        await session.execute(
            update(Run).where(Run.id == run_id).values(heartbeat_at=datetime.now(UTC))
        )

    await _with_session(session_factory, work)


async def _heartbeat_loop(
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    interval: float,
) -> None:
    while True:
        await asyncio.sleep(interval)
        await _touch_heartbeat(session_factory, run_id)
        await bus.publish(run_id, Heartbeat(run_id=str(run_id)))


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


def _prose_decline_question(question: str, reply: str) -> Noul:
    """P2a item 3: does the reply itself say the sources cannot answer?

    Yes only for a whole-question decline (the `says_not_in_sources` shape in
    `evals/abstention.py`); no for a partial answer that states what is
    missing (TR-4 allows that) and for chitchat or library replies.
    """
    return Noul(
        prompt=(
            "Does the following reply decline to answer the question because "
            "the sources do not contain the answer? Answer yes ONLY if the "
            "reply as a whole says the sources cannot answer the question and "
            "gives no substantive answer to it. Answer no if the reply gives "
            "a partial or full answer and merely notes which part the sources "
            "do not cover, or if the reply is small talk, a list of documents, "
            "or otherwise not a source-grounded answer.\n\n"
            f"[question]\n{question}\n\n[reply]\n{reply[:6000]}"
        )
    )


async def _drop_citations(
    session_factory: async_sessionmaker[AsyncSession], message_id: UUID
) -> None:
    """P2a item 3 ( shape): a prose decline is recorded as an
    abstention, and an abstention carries no citations."""

    async def work(session: AsyncSession) -> None:
        await session.execute(delete(Citation).where(Citation.message_id == message_id))

    await _with_session(session_factory, work)


@dataclass
class RunSpec:
    bus: PostgresRunBus
    session_factory: async_sessionmaker[AsyncSession]
    run_id: UUID
    message_id: UUID
    chat_id: UUID
    user_id: UUID
    litellm_model: str
    small_litellm_model: str
    model_id: str
    context_window: int
    mode: str
    source: str
    user_message: str
    run_filters: RunFilters | None = None
    collection_ids: list[UUID] | None = None
    quota_remaining_5h: float | None = None
    settings_version: int | None = None
    instant_title: str | None = None


def start_run(spec: RunSpec) -> None:
    task = asyncio.create_task(execute_run(spec))
    _active_tasks[spec.run_id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(spec.run_id, None))


async def _settle_after_scoring(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    scoring_task: asyncio.Task[None],
) -> None:
    try:
        await scoring_task
    finally:

        async def work(session: AsyncSession) -> None:
            context = get_usage_context()
            snapshot = context.snapshot() if context is not None else None
            await settle_run(session, run_id, snapshot)

        await _with_session(session_factory, work)


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
    abstained: bool,
    plan: str,
    chat_id: UUID,
    instant_title: str | None,
    chitchat: bool = False,
    revert_title: bool = False,
    mode: str = "auto",
    on_first_delta: Callable[[], None] = lambda: None,
    first_token_ms: Callable[[], int | None] = lambda: None,
) -> None:
    """Shared tail for every mode: review phase (skipped for abstentions —
    the fixed template has no claims to verify), event order per delivery
    plan, runs.metrics persistence, fire-and-forget async scoring.

    `chitchat` means "a direct reply that cites nothing and asserts nothing
    about the sources", which now covers a library listing as well as small
    talk. It is deliberately one flag: a second one defaulting to False
    would let a caller that sets one and not the other silently run the
    reviewer and reach a live model. The title is reverted for small talk
    only, so that is its own argument.

    `mode` exists for P2a item 3 only: the prose-decline Noul runs in auto
    mode, where the three broad-question declines were observed.
    """
    final_text = text
    review: ReviewResult | None = None
    suggestions: list[str] = []
    guard: OutputGuardResult | None = None
    blocked = False
    prose_declined = False
    # A direct reply skips the reviewer (no claims, no citations) but is NOT
    # an abstention — its message status is complete (batch A item 3).
    if not abstained and not chitchat:
        # P2a item 3: a reply that says the sources cannot answer becomes an
        # abstention. The Noul rides alongside the review, so it adds no
        # latency post-delivery; a failure classifies as "not declined" —
        # the reply is already on the way, and a classification error must
        # not fail the run.
        decline_task: asyncio.Task[dict[str, Answer] | None] | None = None
        if mode == "auto":

            async def _safe_decline() -> dict[str, Answer] | None:
                try:
                    return await engine.decide(
                        state={"run_id": str(run_id), "kind": "prose_decline"},
                        questions={"prose_decline": _prose_decline_question(question, text)},
                    )
                except Exception:
                    logger.exception("prose-decline Noul failed; keeping the answer as-is")
                    return None

            decline_task = asyncio.create_task(_safe_decline())
        review_coro = _compute_review(
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
        if decline_task is None:
            final_text, review, suggestions, guard = await review_coro
        else:
            (final_text, review, suggestions, guard), decline_answers = await asyncio.gather(
                review_coro, decline_task
            )
            if decline_answers is not None:
                decline_answer = decline_answers["prose_decline"]
                prose_declined = float(decline_answer.value) >= threshold(
                    "prose_decline", decline_answer.engine
                )
        blocked = guard is not None and guard.blocked
        if plan == "hold":
            # The whole reviewed answer goes out as one delta, so this IS the
            # first token a reader sees for a held run.
            on_first_delta()
            await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text=final_text))
        # A prose decline is an abstention: the reply text still lands (above
        # for hold plans), but an abstention shows no claim chips.
        if not prose_declined:
            await _publish_review(
                bus, run_id, review=review, suggestions=suggestions, blocked=blocked
            )
        # plan == "stream" + blocked: the answer already streamed; the
        # blocked verdict replaces the persisted content, which is what a
        # reload shows (TRD §11 "output toxicity (block)").
    if prose_declined:
        await _drop_citations(session_factory, message_id)

    async def refine_title(session: AsyncSession) -> None:
        await refine_chat_title(
            session=session,
            chat_id=chat_id,
            instant_title=instant_title,
            question=question,
            answer=final_text,
            small_model=small_model,
            chitchat=revert_title,
        )

    await _with_session(session_factory, refine_title)

    context = get_usage_context()
    credits: float
    if context is None:
        tokens_out = count_tokens(final_text)
        credits = 0.0
    else:
        tokens_in = context.tokens_in
        tokens_out = context.tokens_out
        credits = context.credits
    latency = {**latency_ms, "generate": generate_ms}
    scores = review.scores if review is not None else None
    # TX-3. Set by the caller through `on_first_delta`, and null when the run
    # published no delta at all (an abstention, or a hold whose plan never
    # reached the generator).
    ttft_ms = first_token_ms()
    # P2a item 3: an abstention carries no review scores, whatever the
    # parallel review computed.
    if prose_declined:
        scores = None
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
            ttft_ms=ttft_ms,
        ),
    )
    metrics: dict[str, object] = {
        "latency_ms": latency,
        "ttft_ms": ttft_ms,
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
    # P2a item 3: a prose decline ends the run as an abstention too — no
    # scoring task, no "complete" status.
    is_abstained = abstained or prose_declined
    status = "abstained" if is_abstained else "complete"
    scoring_task = (
        None
        if is_abstained or chitchat
        else asyncio.create_task(
            score_run_async(run_id=run_id, question=question, answer=final_text, contexts=contexts)
        )
    )
    await _finalize(
        session_factory,
        run_id,
        message_id,
        status=status,
        text=final_text,
        metrics=metrics,
        settle_usage=scoring_task is None,
    )
    if scoring_task is not None:
        _track_background(
            asyncio.create_task(_settle_after_scoring(session_factory, run_id, scoring_task))
        )
    await bus.publish(
        run_id,
        RunCompleted(
            run_id=str(run_id),
            message_id=str(message_id),
            status="abstained" if is_abstained else "completed",
        ),
    )


def _reset_at(exc: AppError) -> str | None:
    """The instant a credit window resets, when the failure carried one.

    `quota/service.py` puts `reset_at` in `QuotaExceeded`'s detail as an
    ISO-8601 string, and it is the only failure that has one: a provider-side
    exhaustion has no window, so it publishes `reset_at: null` rather than a
    guess. A detail of the wrong shape is treated as absent rather than
    stringified, because "try again at <something>" is worse than no time at
    all.
    """
    detail = exc.detail
    if not isinstance(detail, dict):
        return None
    reset_at = detail.get("reset_at")
    return reset_at if isinstance(reset_at, str) else None


async def execute_run(spec: RunSpec) -> None:
    """Run one chat turn: resolve the runtime, then hand it to the mode.

    The mode does its own pipeline (`graph/stages/run_*.py`); this owns the
    parts every run shares — the first-token clock, the heartbeat, the
    terminal event, and the credits that are settled on every exit path.
    """
    bus = spec.bus
    session_factory = spec.session_factory
    run_id = spec.run_id
    message_id = spec.message_id
    chat_id = spec.chat_id
    user_id = spec.user_id
    litellm_model = spec.litellm_model
    small_litellm_model = spec.small_litellm_model
    model_id = spec.model_id
    context_window = spec.context_window
    mode = spec.mode
    source = spec.source
    user_message = spec.user_message
    run_filters = spec.run_filters
    collection_ids = spec.collection_ids
    quota_remaining_5h = spec.quota_remaining_5h
    settings_version = spec.settings_version
    instant_title = spec.instant_title
    # TX-3: the clock for time-to-first-token starts here, before the runtime
    # and model roles are resolved, because everything from here on is latency
    # the person waiting on the chat experiences. It stops at the first
    # `answer.delta` published for this run.
    clock = _FirstTokenClock()
    try:
        setup = await _setup_run(
            session_factory,
            run_id=run_id,
            user_id=user_id,
            quota_remaining_5h=quota_remaining_5h,
            settings_version=settings_version,
        )
    except asyncio.CancelledError:
        await _finalize(session_factory, run_id, message_id, status="cancelled", text="")
        raise
    except BaseException as exc:
        await _fail_setup(bus, session_factory, run_id=run_id, message_id=message_id, exc=exc)
        return

    heartbeat_task: asyncio.Task[None] | None = None
    state = RunState()
    try:
        await bus.publish(
            run_id,
            RunStarted(
                run_id=str(run_id),
                mode=mode,
                source=source,
                model=model_id,
                settings_version=settings_version,
            ),
        )
        await _touch_heartbeat(session_factory, run_id)
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(bus, session_factory, run_id, setup.settings.heartbeat_interval_seconds)
        )
        env = _run_env(
            bus=bus,
            session_factory=session_factory,
            setup=setup,
            run_id=run_id,
            message_id=message_id,
            chat_id=chat_id,
            user_id=user_id,
            litellm_model=litellm_model,
            small_litellm_model=small_litellm_model,
            context_window=context_window,
            mode=mode,
            source=source,
            user_message=user_message,
            run_filters=run_filters,
            collection_ids=collection_ids or [],
            instant_title=instant_title,
            clock=clock,
            state=state,
        )
        await _dispatch(env)
    except asyncio.CancelledError:
        await _finalize(
            session_factory, run_id, message_id, status="cancelled", text=state.text
        )
        try:
            await bus.publish(run_id, RunCancelled(run_id=str(run_id), message_id=str(message_id)))
        finally:
            raise
    except (AppError, Exception) as exc:
        await _fail_run(
            bus,
            session_factory,
            run_id=run_id,
            message_id=message_id,
            user_id=user_id,
            text=state.text,
            exc=exc,
        )
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        reset_usage_context(setup.usage_token)
        reset_runtime_settings(setup.runtime_token)


async def _dispatch(env: RunEnv) -> None:
    """The mode picker (TRD §7 mode table)."""
    if env.mode == "auto":
        await run_auto(env)
        return
    if env.mode == "deep":
        await run_deep(env)
        return
    await run_fast(env)


class _FirstTokenClock:
    """TX-3: time from the start of the run to its first `answer.delta`."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self._first_delta_ms: int | None = None

    def mark(self) -> None:
        if self._first_delta_ms is None:
            self._first_delta_ms = int((time.monotonic() - self._started) * 1000)

    def elapsed_ms(self) -> int | None:
        return self._first_delta_ms


@dataclass(frozen=True)
class _Setup:
    """What a run needs before a mode can start: the settings it was launched
    under, its decision engine, and the context tokens to reset on the way
    out."""

    settings: Settings
    engine: DecisionEngine
    runtime_token: Token[RuntimeSettings | None]
    usage_token: Token[UsageContext | None]


async def _setup_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    user_id: UUID,
    quota_remaining_5h: float | None,
    settings_version: int | None,
) -> _Setup:
    settings = get_settings()
    runtime, model_roles, api_keys = await _runtime_context(session_factory, settings_version)
    usage_context = UsageContext(
        session_factory=session_factory,
        user_id=user_id,
        run_id=run_id,
        model_roles=model_roles,
        api_keys=api_keys,
        remaining_5h=quota_remaining_5h,
    )
    runtime_token = set_runtime_settings(runtime)
    usage_token = set_usage_context(usage_context)
    engine = DecisionEngine(shadow_writer=make_shadow_writer(session_factory))
    engine.configure(runtime)
    return _Setup(
        settings=settings, engine=engine, runtime_token=runtime_token, usage_token=usage_token
    )


async def _fail_setup(
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    message_id: UUID,
    exc: BaseException,
) -> None:
    """A run that never started: nothing streamed, nothing was reserved."""
    if isinstance(exc, AppError):
        await _finalize(session_factory, run_id, message_id, status="failed", text="")
        await bus.publish(
            run_id,
            RunFailed(run_id=str(run_id), error_code=exc.error_code, message=exc.message),
        )
        return
    logger.exception("run setup failed", extra={"run_id": str(run_id)})
    await _finalize(session_factory, run_id, message_id, status="failed", text="")
    await bus.publish(
        run_id,
        RunFailed(
            run_id=str(run_id),
            error_code="run_setup_failed",
            message="The run could not be initialized",
        ),
    )


async def _fail_run(
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    message_id: UUID,
    user_id: UUID,
    text: str,
    exc: BaseException,
) -> None:
    """The one place every terminal failure lands (TRD §7)."""
    if isinstance(exc, AppError):
        logger.error("run failed", extra={"run_id": str(run_id), "error_code": exc.error_code})
        signals.emit(signals.RUN_FAILED, run_id=run_id, user_id=user_id, error_code=exc.error_code)
        await _finalize(session_factory, run_id, message_id, status="failed", text=text)
        await bus.publish(
            run_id,
            RunFailed(
                run_id=str(run_id),
                error_code=exc.error_code,
                message=exc.message,
                reset_at=_reset_at(exc),
            ),
        )
        return
    await _fail_at_provider(bus, session_factory, run_id, message_id, user_id, text, exc)


async def _fail_at_provider(
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    message_id: UUID,
    user_id: UUID,
    text: str,
    exc: BaseException,
) -> None:
    """A provider failure is not an unknown failure.

    An invalid key, an exhausted balance and an unreachable provider each get
    their own code, because for all three "try again" is the wrong instruction
    and for two of them it is also the wrong audience. Classified from the
    exception itself rather than by wrapping it at each call site.
    """
    provider_error = classify_provider_error(exc)
    if provider_error is None:
        logger.exception("run failed", extra={"run_id": str(run_id)})
        signals.emit(signals.RUN_FAILED, run_id=run_id, user_id=user_id, error_code="run_error")
        await _finalize(session_factory, run_id, message_id, status="failed", text=text)
        await bus.publish(
            run_id,
            RunFailed(
                run_id=str(run_id),
                error_code="run_error",
                message="The run failed before completing",
            ),
        )
        return
    logger.error(
        "run failed at the provider",
        extra={"run_id": str(run_id), "error_code": provider_error.error_code},
    )
    signals.emit(
        signals.RUN_FAILED,
        run_id=run_id,
        user_id=user_id,
        error_code=provider_error.error_code,
    )
    # A provider that is out of credit is a separate alarm from a run that
    # failed: one user is affected by `run.failed`, every user is blocked until
    # it is topped up. `provider.credit_low` fires on the 402/quota codes only,
    # so a provider being merely down does not page anyone about money.
    if provider_error.error_code == "quota_exceeded":
        signals.emit(
            signals.PROVIDER_CREDIT_LOW,
            run_id=run_id,
            user_id=user_id,
            error_code=provider_error.error_code,
        )
    await _finalize(session_factory, run_id, message_id, status="failed", text=text)
    await bus.publish(
        run_id,
        RunFailed(
            run_id=str(run_id),
            error_code=provider_error.error_code,
            message=provider_error.message,
        ),
    )


def _run_env(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    setup: _Setup,
    run_id: UUID,
    message_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    litellm_model: str,
    small_litellm_model: str,
    context_window: int,
    mode: str,
    source: str,
    user_message: str,
    run_filters: RunFilters | None,
    collection_ids: list[UUID],
    instant_title: str | None,
    clock: _FirstTokenClock,
    state: RunState,
) -> RunEnv:
    """The environment a mode stage runs in."""
    return RunEnv(
        bus=bus,
        session_factory=session_factory,
        engine=setup.engine,
        run_id=run_id,
        message_id=message_id,
        chat_id=chat_id,
        user_id=user_id,
        litellm_model=litellm_model,
        small_model=small_litellm_model,
        context_window=context_window,
        mode=mode,
        source=source,
        user_message=user_message,
        client_filters=to_client_filters(run_filters),
        collection_ids=collection_ids,
        instant_title=instant_title,
        heartbeat_interval_seconds=setup.settings.heartbeat_interval_seconds,
        coalesce_seconds=setup.settings.delta_coalesce_ms / 1000,
        touch_heartbeat=lambda: _touch_heartbeat(session_factory, run_id),
        emit_decision=_emit_decision(bus, run_id),
        mark_first_delta=clock.mark,
        first_token_ms=clock.elapsed_ms,
        state=state,
        finish=lambda request: _finish_run(
            bus=bus,
            session_factory=session_factory,
            setup=setup,
            run_id=run_id,
            message_id=message_id,
            chat_id=chat_id,
            context_window=context_window,
            litellm_model=litellm_model,
            small_model=small_litellm_model,
            instant_title=instant_title,
            mode=mode,
            clock=clock,
            request=request,
        ),
    )


def _emit_decision(
    bus: PostgresRunBus, run_id: UUID
) -> Callable[[str, Answer, DecisionCall], Awaitable[None]]:
    async def emit(name: str, answer: Answer, call: DecisionCall) -> None:
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
                stage=call.stage,
                call_id=call.call_id,
                batch_size=call.batch_size,
                threshold=display_threshold(name, answer.engine),
            ),
        )

    return emit


async def _finish_run(
    *,
    bus: PostgresRunBus,
    session_factory: async_sessionmaker[AsyncSession],
    setup: _Setup,
    run_id: UUID,
    message_id: UUID,
    chat_id: UUID,
    context_window: int,
    litellm_model: str,
    small_model: str,
    instant_title: str | None,
    mode: str,
    clock: _FirstTokenClock,
    request: FinishRequest,
) -> None:
    """The shared tail for every mode, from one mode's finish request."""
    await _finish_answer(
        bus=bus,
        session_factory=session_factory,
        engine=setup.engine,
        run_id=run_id,
        message_id=message_id,
        question=request.question,
        text=request.text,
        contexts=request.contexts,
        latency_ms=request.latency_ms,
        context_used=request.context_used,
        context_window=context_window,
        litellm_model=litellm_model,
        small_model=small_model,
        tokens_in=request.tokens_in,
        generate_ms=request.generate_ms,
        abstained=request.abstained,
        chitchat=request.chitchat,
        revert_title=request.revert_title,
        plan=request.plan,
        chat_id=chat_id,
        instant_title=instant_title,
        mode=mode,
        on_first_delta=clock.mark,
        first_token_ms=clock.elapsed_ms,
    )


async def sweep_stale_runs(
    bus: PostgresRunBus, session_factory: async_sessionmaker[AsyncSession]
) -> int:
    """Mark runs in `running` with no heartbeat for 60 s failed (TRD §7)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=get_settings().heartbeat_sweep_seconds)

    async def work(session: AsyncSession) -> list[tuple[UUID, UUID]]:
        candidates = (
            (
                await session.execute(
                    select(Run.id).where(
                        Run.status == "running",
                        Run.heartbeat_at.is_not(None),
                        Run.heartbeat_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        # The staleness predicate is repeated in the UPDATE, not trusted from
        # the SELECT above: a run that heartbeats in between is alive, and
        # matching on id alone failed it anyway — then settled its usage and
        # published a false terminal failure (review S7). RETURNING names the
        # rows this sweep actually took, so only those are touched below.
        swept = (
            await session.execute(
                update(Run)
                .where(
                    Run.id.in_(candidates),
                    Run.status == "running",
                    Run.heartbeat_at.is_not(None),
                    Run.heartbeat_at < cutoff,
                )
                .values(status="failed")
                .returning(Run.id, Run.message_id)
            )
        ).all()
        for run_id, message_id in swept:
            message = await session.get(Message, message_id)
            if message is not None and message.status is None:
                message.status = "failed"
            await settle_run(session, run_id, None)
        return [(row[0], row[1]) for row in swept]

    stale = await _with_session(session_factory, work)
    for run_id, _message_id in stale:
        # `worker.stalled`, not `run.failed`: this is the one failure whose
        # cause is our own process rather than a user or a provider, so an
        # operator paging on it is looking at the right thing. It arrives
        # here and nowhere else — a stalled worker cannot emit anything
        # itself, which is the whole reason the sweeper reports it.
        signals.emit(
            signals.WORKER_STALLED,
            run_id=run_id,
            error_code="heartbeat_timeout",
            sweep_seconds=get_settings().heartbeat_sweep_seconds,
        )
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
