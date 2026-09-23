"""Deep mode (TRD §7 row 5, CH-4): Planner → parallel hop retrieve →
Controller loop (stops at `deep_max_hops` or the credit budget) → generate.

Deep always plans and always multi-hops — it does not run Ingress's
`complexity` decision to pick single vs multi like Auto does (CH-4)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from db.models import Chat, Citation, Message
from decisions import DecisionEngine
from graph import rewrite as rewrite_node
from graph.abstain import build_abstain_event, stream_abstention
from graph.controller import controller_decide
from graph.generate import stream_grounded_answer
from graph.hop_retrieve import HopNote, ready_sub_questions, run_hop_batch
from graph.ingress import IngressOutcome, run_ingress
from graph.planner import generate_followup, plan_question
from graph.timing import EventPublisher, make_step_timer
from providers.llm import complete
from quota.usage import get_usage_context
from retrieval.context import count_tokens, trim_context
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.filters import ClientFilters
from retrieval.hybrid import ScoredChunk
from retrieval.web import ensure_web_chunks
from runtime import runtime_value
from schemas.decisions import Answer
from schemas.events import Abstain, Decision, Plan, Retrieval, SubQuestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeepRunInput:
    run_id: UUID
    message_id: UUID
    chat_id: UUID
    user_id: UUID
    question: str
    litellm_model: str
    small_model: str
    context_window: int
    source: str
    client_filters: ClientFilters
    collection_ids: list[UUID]


@dataclass
class DeepRun:
    params: DeepRunInput
    history: list[tuple[str, str]]
    contexts: list[ExpandedContext]
    kept_chunks: list[ScoredChunk]
    dropped_chunks: list[ScoredChunk]
    rewritten: str
    plan_event: Plan
    retrieval_events: list[Retrieval]
    decision_events: list[Decision]
    abstain_event: Abstain | None
    latency_ms: dict[str, int]
    context_used: int
    ingress: IngressOutcome
    credits_used: int

    async def stream_answer_with_thinking(self) -> AsyncIterator[tuple[str, str]]:
        """Yields `("content", text)` / `("thinking", text)` pairs — the
        runner decides whether each becomes an AnswerDelta or a
        ThinkingDelta event; this keeps DeepRun the only place that needs
        an interleaving queue (fast/auto stream plain content)."""
        if self.abstain_event is not None:
            async for token in stream_abstention(self.abstain_event):
                yield ("content", token)
            return

        queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()

        async def on_reasoning(text: str) -> None:
            await queue.put(("thinking", text))

        async def produce() -> None:
            async for token in stream_grounded_answer(
                litellm_model=self.params.litellm_model,
                question=self.rewritten,
                contexts=self.contexts,
                history=self.history,
                metadata={
                    "run_id": str(self.params.run_id),
                    "user_id": str(self.params.user_id),
                },
                on_reasoning=on_reasoning,
            ):
                await queue.put(("content", token))
            await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            await task


async def _history(
    session: AsyncSession, chat_id: UUID, exclude_message_id: UUID
) -> list[tuple[str, str]]:
    messages = (
        (
            await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id, Message.id != exclude_message_id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [(m.role, m.content) for m in messages if m.content]


def _decision_event(run_id: UUID, name: str, answer: Answer) -> Decision:
    return Decision(
        run_id=str(run_id),
        name=name,
        value=answer.value,
        probability=answer.probability,
        probabilities=answer.probabilities,
        engine=answer.engine,
        latency_ms=answer.latency_ms,
        reasoning=answer.reasoning,
    )


def _rerank_score_key(chunk: ScoredChunk) -> float:
    return chunk.rerank_score if chunk.rerank_score is not None else chunk.fused_score


async def prepare_deep_run(
    session_factory: async_sessionmaker[AsyncSession],
    params: DeepRunInput,
    engine: DecisionEngine,
    *,
    publish: EventPublisher | None = None,
) -> DeepRun:
    """Run ingress + rewrite + plan + hop loop (parallel per hop, Controller
    gate between hops) + trim; returns everything the runner needs to
    stream the answer."""
    settings = get_settings()
    hop_limit = int(runtime_value("retrieval.hop_limit", settings.deep_max_hops))
    usage_context = get_usage_context()
    credit_budget = float(runtime_value("deep.per_run_credit_cap", settings.deep_credit_budget))
    if usage_context is not None and usage_context.remaining_5h is not None:
        credit_budget = min(credit_budget, float(usage_context.remaining_5h))
    decision_events: list[Decision] = []
    retrieval_events: list[Retrieval] = []
    latency_ms: dict[str, int] = {}
    _step = make_step_timer(
        node="deep", run_id=params.run_id, latency_ms=latency_ms, publish=publish
    )

    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, params.chat_id)
        history = await _history(session, params.chat_id, params.message_id)
        summary = chat.summary if chat is not None else None
        has_collections = bool(params.collection_ids)

        async def ingress_work() -> IngressOutcome:
            outcome = await run_ingress(
                engine,
                run_id=params.run_id,
                user_message=params.question,
                has_collections=has_collections,
            )
            for name, answer in outcome.answers.items():
                decision_events.append(_decision_event(params.run_id, name, answer))
            return outcome

        async def rewrite_work() -> str:
            return await rewrite_node.rewrite_query(
                question=params.question,
                history=history,
                summary=summary,
                small_model=params.small_model,
                complete_fn=complete,
            )

        async def ingress_and_rewrite() -> tuple[IngressOutcome, str]:
            return await asyncio.gather(ingress_work(), rewrite_work())

        ingress, rewritten = await _step("ingress+rewrite", ingress_and_rewrite)
        empty_plan = Plan(run_id=str(params.run_id), sub_questions=[])

        if ingress.blocked:
            abstain = Abstain(
                run_id=str(params.run_id),
                found_summary="",
                missing_summary=(
                    "This message was blocked because it appears to attempt "
                    "to manipulate the assistant or extract hidden state."
                ),
                offered_actions=[],
            )
            return DeepRun(
                params=params,
                history=history,
                contexts=[],
                kept_chunks=[],
                dropped_chunks=[],
                rewritten=params.question,
                plan_event=empty_plan,
                retrieval_events=[],
                decision_events=decision_events,
                abstain_event=abstain,
                latency_ms=latency_ms,
                context_used=0,
                ingress=ingress,
                credits_used=0,
            )

        source_filter = params.source
        if params.source == "auto":
            source_filter = ingress.source
        if source_filter in {"web", "both"}:
            await ensure_web_chunks(session, query=params.question, chat_id=params.chat_id)

        plan = await _step(
            "plan",
            lambda: plan_question(rewritten, small_model=params.small_model, complete_fn=complete),
        )
        plan_event = Plan(
            run_id=str(params.run_id),
            sub_questions=[
                SubQuestion(id=sq.id, question=sq.question, depends_on=sq.depends_on) for sq in plan
            ],
        )

        answered_ids: set[str] = set()
        all_kept: list[ScoredChunk] = []
        all_dropped: list[ScoredChunk] = []
        notes: list[str] = []
        hop_index = 0
        credits_used = 0
        sufficient = False
        followup_count = 0
        dynamic_plan = list(plan)

        while hop_index < hop_limit and (
            usage_context is None or usage_context.credits < credit_budget
        ):
            batch = ready_sub_questions(dynamic_plan, answered_ids)
            if not batch:
                if hop_index == 0:
                    break  # plan_question always returns >=1 sub-question
                # Controller said need_more but the upfront plan is fully
                # answered — generate one more targeted sub-question rather
                # than abstaining with hop/credit budget still unused.
                followup_count += 1
                next_id = f"followup{followup_count}"

                async def _make_followup(next_id: str = next_id) -> SubQuestion | None:
                    return await generate_followup(
                        rewritten,
                        "\n\n".join(notes),
                        small_model=params.small_model,
                        complete_fn=complete,
                        next_id=next_id,
                    )

                followup = await _step(f"followup_{followup_count}", _make_followup)
                if followup is None:
                    break
                dynamic_plan.append(followup)
                batch = [followup]
            hop_index += 1
            this_hop = hop_index

            async def _run_this_hop(
                batch: list[SubQuestion] = batch, this_hop: int = this_hop
            ) -> list[HopNote]:
                return await run_hop_batch(
                    batch,
                    session=session,
                    engine=engine,
                    run_id=params.run_id,
                    hop_index=this_hop,
                    user_id=params.user_id,
                    collection_ids=list(params.collection_ids),
                    chat_id=params.chat_id,
                    client_filters=params.client_filters,
                    lexical_weight=ingress.lexical_weight,
                )

            hop_notes = await _step(f"hop_{hop_index}", _run_this_hop)
            for hop_note in hop_notes:
                answered_ids.add(hop_note.sub_question.id)
                notes.append(hop_note.note)
                all_kept.extend(hop_note.kept_chunks)
                all_dropped.extend(hop_note.dropped_chunks)
                retrieval_events.append(hop_note.retrieval_event)
                for name, answer in hop_note.decision_answers.items():
                    decision_events.append(_decision_event(params.run_id, name, answer))
                if usage_context is None:
                    credits_used += count_tokens(hop_note.note)

            sufficient, controller_answer = await _step(
                f"controller_{hop_index}",
                lambda: controller_decide(
                    engine,
                    run_id=str(params.run_id),
                    question=rewritten,
                    notes="\n\n".join(notes),
                ),
            )
            decision_events.append(_decision_event(params.run_id, "controller", controller_answer))
            if sufficient:
                break

        abstain_event: Abstain | None = None
        contexts: list[ExpandedContext] = []
        winners = dedupe_adjacent(sorted(all_kept, key=_rerank_score_key, reverse=True))

        if not sufficient:
            abstain_event = build_abstain_event(
                str(params.run_id), winners, offered_actions=["web"]
            )
        else:
            contexts = await expand_context(session, winners)

        history_tokens = sum(count_tokens(text) for _, text in history[-6:])
        contexts, context_used = trim_context(
            contexts, window_tokens=params.context_window, history_tokens=history_tokens
        )
        session.add_all(
            Citation(
                message_id=params.message_id,
                n=i + 1,
                chunk_id=context.chunk.chunk_id,
                rerank_score=context.chunk.rerank_score,
            )
            for i, context in enumerate(contexts)
        )

    return DeepRun(
        params=params,
        history=history,
        contexts=contexts,
        kept_chunks=all_kept,
        dropped_chunks=all_dropped,
        rewritten=rewritten,
        plan_event=plan_event,
        retrieval_events=retrieval_events,
        decision_events=decision_events,
        abstain_event=abstain_event,
        latency_ms=latency_ms,
        context_used=context_used,
        ingress=ingress,
        credits_used=credits_used,
    )


async def finalize_deep_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: DeepRun,
    *,
    generate_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Post-delivery: refresh the rolling summary if due (same as Auto)."""
    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, run.params.chat_id)
        await rewrite_node.maybe_refresh_summary(
            session,
            chat_id=run.params.chat_id,
            summary=chat.summary if chat is not None else None,
            small_model=run.params.small_model,
            complete_fn=complete,
        )
