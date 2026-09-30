"""Auto mode pipeline (TRD §7 mode table): ingress (parallel with rewrite)
→ multi-query hybrid retrieval → rerank → sanitizer → small-to-big →
sufficient-check retry loop → conflict check → generate. On insufficient
evidence after retries the run abstains (TR-4).

Auto always runs this single-hop-with-multi-query-fusion path regardless
of ingress's `complexity` verdict — Plan/Hop/Controller multi-hop lives in
Deep mode (graph/deep.py, TRD §17 row 5), which the user reaches directly
via the mode picker rather than through an Auto complexity branch.
"""

import asyncio
import logging
import math
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chats.scope import list_scope_documents
from db.models import Chat, Citation, Message
from decisions import DecisionEngine, threshold
from decisions.sanitize import sanitize_chunks
from graph import rewrite as rewrite_node
from graph.abstain import build_abstain_event, stream_abstention
from graph.generate import (
    stream_chitchat_reply,
    stream_grounded_answer,
    stream_library_reply,
)
from graph.ingress import IngressOutcome, run_ingress
from graph.rewrite import CompleteFn
from graph.timing import EventPublisher, make_step_timer
from providers.llm import complete
from retrieval.cache import get_query_embedding
from retrieval.context import count_tokens, trim_context
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import ScoredChunk, hybrid_search
from retrieval.rerank import (
    RERANK_TOP_N,
    JevRerank,
    RerankProvider,
    apply_rerank,
    get_reranker,
)
from retrieval.web import ensure_web_chunks
from runtime import runtime_value
from schemas.decisions import Noul
from schemas.events import (
    Abstain,
    Conflict,
    Decision,
    Retrieval,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 240
MULTI_QUERY_VARIANTS = 3
# A multi-part question ("... and how does she answer?") retrieves on the
# whole question as one query, so the part after the "and" is out of the
# question the embedding encodes and its chunks never surface — that is why
# the Darcy turn in `make smoke` abstained (KI-12). One extra small-role call
# lists the parts; each becomes its own retrieval and, through `provenance`,
# its own equal share of the top-k in `_rerank_candidates`.
# Parts-only instruction: the phrasings call above already produced the
# compound rephrasings, so asking for them again here made compliant models
# (gpt-4o-mini and the free Nemotron both do) emit phrasings first and parts
# last — and the old parser stopped at the phrasings, so every "part" came
# back compound (KI-12 item 1, proved by capture 2026-09-29).
MULTI_PART_VARIANTS = 3
MULTI_PARTS = (
    "The question above has more than one part. List each part of the "
    "question restated as a standalone search query that keeps that part's "
    "own subject, one per line. Do not answer them and do not merge them. "
    "No commentary."
)
# Answer-first (batch A, owner-approved): one retrieve, and below the
# sufficient_abstain floor exactly one rewrite + retry before abstaining.
# The retry loop in prepare_auto_run clamps any admin override to this.
MAX_SUFFICIENT_RETRIES = 1
TOP_CHUNKS_FOR_SUFFICIENT = 5
SUFFICIENT_EVIDENCE_CHARS = 9_000

# Greeting fast path (batch A, owner-approved carve-out from "all
# classification through DecisionEngine"): a raw message of at most 40
# chars whose normalised form is one of these phrases skips ingress and
# retrieval entirely. The generator only ever sees the CANONICAL phrase
# from this set, never the raw text, so invisible-character smuggling
# (zero-width, Unicode tag characters) cannot reach the model.
GREETING_ALLOWLIST = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "thanks a lot",
        "bye",
        "goodbye",
        "good morning",
        "good afternoon",
        "good evening",
        "ok",
        "okay",
        "cool",
        "great",
    }
)
MAX_GREETING_CHARS = 40
MAX_GREETING_WORDS = 4


def greeting_canonical(raw: str) -> str | None:
    """The canonical allowlist phrase the raw message normalises to, or
    None. Non-letters become spaces (not deleted) before collapsing, so
    "g-o-o-d" stays four words and can never reassemble into a greeting."""
    if len(raw) > MAX_GREETING_CHARS:
        return None
    normalized = unicodedata.normalize("NFKC", raw).lower()
    letters = "".join(c if c.isalpha() or c.isspace() else " " for c in normalized)
    words = letters.split()
    if len(words) > MAX_GREETING_WORDS:
        return None
    candidate = " ".join(words)
    return candidate if candidate in GREETING_ALLOWLIST else None
# Round 2 (KI-12): the per-source head window is gone. It measured better
# on faithfulness (2026-09-28, batch 5/6) only because the judge saw the
# first 250 chars of a 500-token child and the Darcy proposal lives in a
# child's last sentence — the head window hid the evidence. Children are
# now ~300 tokens, so each source contributes its whole child; parent
# context follows only if the ~9,000-character total has room.


@dataclass(frozen=True)
class AutoRunInput:
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
class AutoRun:
    params: AutoRunInput
    history: list[tuple[str, str]]
    contexts: list[ExpandedContext]
    kept_chunks: list[ScoredChunk]
    dropped_chunks: list[ScoredChunk]
    rewritten: str
    retrieval_events: list[Retrieval]
    decision_events: list[Decision]
    conflict_event: Conflict | None
    abstain_event: Abstain | None
    latency_ms: dict[str, int]
    context_used: int
    ingress: IngressOutcome
    chitchat: bool = False
    sufficiency_p: float = 0.0
    library_names: list[str] | None = None

    async def stream_answer(self) -> AsyncIterator[str]:
        if self.chitchat:
            async for token in stream_chitchat_reply(
                litellm_model=self.params.litellm_model,
                message=self.rewritten,
                history=self.history,
                metadata={
                    "run_id": str(self.params.run_id),
                    "user_id": str(self.params.user_id),
                },
            ):
                yield token
            return
        if self.library_names is not None:
            async for token in stream_library_reply(
                litellm_model=self.params.litellm_model,
                question=self.rewritten,
                names=self.library_names,
                history=self.history,
                metadata={
                    "run_id": str(self.params.run_id),
                    "user_id": str(self.params.user_id),
                },
            ):
                yield token
            return
        if self.abstain_event is not None:
            # Abstention path: the fixed-template output is generated by
            # the same streaming generator with a directive prompt — the
            # LLM only renders the template, not free-form text (TR-4).
            async for token in _stream_abstention(self):
                yield token
            return
        async for token in stream_grounded_answer(
            litellm_model=self.params.litellm_model,
            question=self.rewritten,
            contexts=self.contexts,
            history=self.history,
            metadata={
                "run_id": str(self.params.run_id),
                "user_id": str(self.params.user_id),
            },
        ):
            yield token


async def _history(
    session: AsyncSession, chat_id: UUID, exclude_message_id: UUID
) -> list[tuple[str, str]]:
    from sqlalchemy import select

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


async def _generate_query_variants(
    question: str, small_model: str, complete_fn: CompleteFn, n: int, instruction: str | None = None
) -> list[str]:
    """Multi-query rewrite (TRD §7 mode table, Auto only). n variants in
    one LLM call; first variant is the rewritten query itself. With
    `instruction` the call asks for that shape instead (see MULTI_PARTS),
    so the parsed lines are returned as-is, without the question seeded."""
    if n <= 1 and instruction is None:
        return [question]
    from prompts.load import load_prompt

    prompt_template = load_prompt("rewrite.md")
    prompt = prompt_template.format(
        summary="(none — query-variant generation)",
        history="(none)",
        question=question,
    )
    if instruction is None:
        prompt += (
            f"\n\nProduce {n} alternative phrasings of the rewritten question, "
            f"one per line. Each should target a different retrieval angle "
            f"(synonyms, narrower scope, broader scope). No commentary."
        )
    else:
        prompt += f"\n\n{instruction}"
    response = await complete_fn(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": question}],
        metadata={"role": "rewriter"},
    )
    variants = [question] if instruction is None else []
    for line in response.strip().splitlines():
        line = line.strip().lstrip("0123456789.-) ")
        if line and line not in variants:
            variants.append(line)
        if len(variants) >= n:
            break
    return variants[:n]


def _fuse_multi_query(result_sets: list[list[ScoredChunk]]) -> list[ScoredChunk]:
    """Reciprocal-rank fusion across query variants."""
    if not result_sets:
        return []
    if len(result_sets) == 1:
        return result_sets[0]
    rrf_k = 60
    fused: dict[UUID, tuple[ScoredChunk, float]] = {}
    for chunks in result_sets:
        for rank, chunk in enumerate(chunks, start=1):
            score = 1.0 / (rrf_k + rank)
            if chunk.chunk_id in fused:
                existing, existing_score = fused[chunk.chunk_id]
                fused[chunk.chunk_id] = (existing, existing_score + score)
            else:
                fused[chunk.chunk_id] = (chunk, score)
    ordered = sorted(fused.values(), key=lambda item: item[1], reverse=True)
    from dataclasses import replace as dc_replace

    return [dc_replace(chunk, fused_score=score) for chunk, score in ordered]


def _entity_queries(question: str, intent: str) -> list[str]:
    """One retrieval per named entity in a compare question."""
    # ponytail: capitalised-noun regex — misses ALL-CAPS titles, quoted names
    # and lowercase proper nouns, and treats a sentence-initial word as a name.
    # Reuse the entities the rewrite step already produces instead of parsing
    # them again here if compare coverage matters.
    if intent != "compare":
        return []
    entities = [
        re.sub(r"^(?:Compare|How|What|Why|When|Where|Who)\s+", "", entity)
        for entity in re.findall(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|the))*(?=\b)", question)
        if entity not in {"Compare", "How", "What", "Why", "When", "Where", "Who"}
    ]
    return list(dict.fromkeys(entities))


def _add_rerank_scores(events: list[Retrieval], reranked: list[ScoredChunk]) -> None:
    scores = {str(chunk.chunk_id): chunk.rerank_score for chunk in reranked}
    for event in events:
        for chunk in event.chunks:
            if chunk.chunk_id in scores:
                chunk.rerank_score = scores[chunk.chunk_id]


async def _rerank_candidates(
    reranker: RerankProvider,
    *,
    query: str,
    chunks: list[ScoredChunk],
    provenance: dict[UUID, str],
    limit: int,
) -> list[ScoredChunk]:
    """Rerank the fused set, except when a compare run's chunks came from
    several named entities: rerank each entity's own set and take an equal
    share of `limit` from each, so the second book can't be scored out of
    the top-k entirely (KI-12). The "" group is the chunks no entity
    surfaced; it takes a share too, reranked on the original query."""
    groups: dict[str, list[ScoredChunk]] = {}
    for chunk in chunks:
        groups.setdefault(provenance.get(chunk.chunk_id, ""), []).append(chunk)
    if len(groups) < 2:
        return await apply_rerank(reranker, query=query, chunks=chunks, top_n=limit)
    share = math.ceil(limit / len(groups))
    picked: list[ScoredChunk] = []
    for label, group in groups.items():
        picked.extend(
            await apply_rerank(reranker, query=label or query, chunks=group, top_n=share)
        )
    # Order by rerank score, not group insertion order. Dict order put the
    # "" (no-entity) share first whatever it scored, so a compare run's
    # citations [1]-[3] could be the weakest passages (compare-inventors
    # cited Noli Me Tangere at 0.01-0.02 ahead of Frankenstein and The
    # Time Machine). The shares stay the same; only the order changes.
    picked.sort(key=lambda chunk: chunk.rerank_score or 0.0, reverse=True)
    return picked


def _sufficient_question(question: str, top_contexts: list[ExpandedContext]) -> Noul:
    remaining = SUFFICIENT_EVIDENCE_CHARS
    entries: list[str] = []
    # Whole children first, in rank order; parent context follows only if
    # the budget has room after every child that fits took its turn. The
    # previous interleaving (each entry's parent before the next entry's
    # child) let the first source's parent eat the budget, which is how
    # compare-inventors' sufficiency judge saw only Noli Me Tangere (D2
    # item 3): entry 1 child + ±1 neighbours ≈ 4,000 chars, so a
    # 9,000-char budget held ~2 entries.
    for i, context in enumerate(top_contexts):
        if remaining <= 0:
            break
        text = context.chunk.text[:remaining]
        remaining -= len(text)
        entries.append(f"[{i + 1}] [matched passage]\n{text}")
    parents: list[str] = []
    for i, context in enumerate(top_contexts):
        if remaining <= 0 or i >= len(entries):
            break
        parent = context.context_text
        if parent == context.chunk.text:
            continue
        excerpt = parent[:remaining]
        parents.append(f"[{i + 1}] [parent context]\n{excerpt}")
        remaining -= len(excerpt)
    evidence = "\n\n".join([*entries, *parents]) or "(no evidence retrieved)"
    return Noul(
        prompt=(
            "Do the following retrieved chunks together contain enough "
            "evidence to answer the question correctly and completely? "
            "Answer yes only if the answer is fully grounded in the "
            f"evidence.\n\n[question]\n{question}\n\n[evidence]\n{evidence}"
        )
    )


def _conflict_question(top_chunks: list[ScoredChunk]) -> Noul:
    remaining = SUFFICIENT_EVIDENCE_CHARS
    entries: list[str] = []
    for i, chunk in enumerate(top_chunks):
        if remaining <= 0:
            break
        text = chunk.text[:remaining]
        remaining -= len(text)
        entries.append(f"[{i + 1}] (doc: {chunk.document_name or chunk.source_type}) {text}")
    evidence = "\n\n".join(entries)
    return Noul(
        prompt=(
            "Do any two of the following chunks disagree about a fact the "
            "question depends on? Yes only if both chunks assert "
            f"incompatible claims.\n\n{evidence}"
        )
    )


async def prepare_auto_run(
    session_factory: async_sessionmaker[AsyncSession],
    params: AutoRunInput,
    engine: DecisionEngine,
    *,
    publish: EventPublisher | None = None,
) -> AutoRun:
    """Run ingress + rewrite + multi-query retrieval + rerank + sanitize +
    sufficient-check retry + conflict check; returns everything the runner
    needs to stream the answer."""

    decision_events: list[Decision] = []
    retrieval_events: list[Retrieval] = []
    latency_ms: dict[str, int] = {}

    _step = make_step_timer(
        node="auto", run_id=params.run_id, latency_ms=latency_ms, publish=publish
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
                decision_events.append(
                    Decision(
                        run_id=str(params.run_id),
                        name=name,
                        value=answer.value,
                        probability=answer.probability,
                        probabilities=answer.probabilities,
                        engine=answer.engine,
                        latency_ms=answer.latency_ms,
                        reasoning=answer.reasoning,
                    )
                )
            return outcome

        async def rewrite_work() -> str:
            return await rewrite_node.rewrite_query(
                question=params.question,
                history=history,
                summary=summary,
                small_model=params.small_model,
                complete_fn=complete,
            )

        async def _skip_retrieval() -> None:
            return None

        canonical_greeting = greeting_canonical(params.question)
        if canonical_greeting is not None:
            await _step("Greeting fast path: skipped ingress", _skip_retrieval)
            return AutoRun(
                params=params,
                history=history,
                contexts=[],
                kept_chunks=[],
                dropped_chunks=[],
                rewritten=canonical_greeting,
                retrieval_events=[],
                decision_events=[],
                conflict_event=None,
                abstain_event=None,
                latency_ms=latency_ms,
                context_used=0,
                ingress=IngressOutcome(
                    intent="chitchat",
                    source="upload",
                    complexity="single",
                    risk="low",
                    lexical_weight=0.5,
                    guard_injection="pass",
                    guard_jailbreak="pass",
                    guard_pii="pass",
                    off_topic="pass",
                ),
                chitchat=True,
            )

        async def ingress_and_rewrite() -> tuple[IngressOutcome, str]:
            ingress_result, rewritten_result = await asyncio.gather(ingress_work(), rewrite_work())
            return ingress_result, rewritten_result

        ingress, rewritten = await _step("ingress+rewrite", ingress_and_rewrite)

        if ingress.intent == "chitchat" and ingress.off_topic != "block":
            await _step("Small talk: skipped retrieval", _skip_retrieval)
            return AutoRun(
                params=params,
                history=history,
                contexts=[],
                kept_chunks=[],
                dropped_chunks=[],
                rewritten=params.question,
                retrieval_events=[],
                decision_events=decision_events,
                conflict_event=None,
                abstain_event=None,
                latency_ms=latency_ms,
                context_used=0,
                ingress=ingress,
                chitchat=True,
            )

        if ingress.intent == "library":
            await _step("Library: skipped retrieval", _skip_retrieval)
            names = [
                document.name
                for document in await list_scope_documents(
                    session, list(params.collection_ids)
                )
            ]
            return AutoRun(
                params=params,
                history=history,
                contexts=[],
                kept_chunks=[],
                dropped_chunks=[],
                rewritten=params.question,
                retrieval_events=[],
                decision_events=decision_events,
                conflict_event=None,
                abstain_event=None,
                latency_ms=latency_ms,
                context_used=0,
                ingress=ingress,
                library_names=names,
            )

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
            return AutoRun(
                params=params,
                history=history,
                contexts=[],
                kept_chunks=[],
                dropped_chunks=[],
                rewritten=params.question,
                retrieval_events=[],
                decision_events=decision_events,
                conflict_event=None,
                abstain_event=abstain,
                latency_ms=latency_ms,
                context_used=0,
                ingress=ingress,
            )

        source_filter = params.source
        if params.source == "auto":
            source_filter = ingress.source

        if source_filter in {"web", "both"}:
            await ensure_web_chunks(
                session,
                query=params.question,
                chat_id=params.chat_id,
                optional=source_filter == "both",
            )

        async def retrieve_queries(
            query: str,
        ) -> tuple[list[ScoredChunk], list[Retrieval], dict[UUID, str]]:
            variants = await _generate_query_variants(
                query, params.small_model, complete, MULTI_QUERY_VARIANTS
            )
            parts: list[str] = []
            if ingress.intent == "multi-part":
                parts = await _generate_query_variants(
                    query,
                    params.small_model,
                    complete,
                    MULTI_PART_VARIANTS,
                    instruction=MULTI_PARTS,
                )
            part_queries = [
                candidate
                for candidate in (
                    *_entity_queries(params.question, ingress.intent),
                    *parts,
                )
                if candidate not in variants
            ]
            variants.extend(part_queries)
            result_sets: list[list[ScoredChunk]] = []
            events: list[Retrieval] = []
            provenance: dict[UUID, str] = {}
            for variant in variants:
                embedding = await get_query_embedding(session, variant)
                ownership = Ownership(
                    user_id=params.user_id,
                    collection_ids=list(params.collection_ids),
                    chat_id=params.chat_id,
                )
                fused = await hybrid_search(
                    session,
                    query_text=variant,
                    query_embedding=embedding,
                    ownership=ownership,
                    filters=params.client_filters,
                    lexical_weight=ingress.lexical_weight,
                )
                result_sets.append(fused)
                if variant in part_queries:
                    for c in fused:
                        provenance.setdefault(c.chunk_id, variant)
                events.append(
                    Retrieval(
                        run_id=str(params.run_id),
                        hop=0,
                        query=variant,
                        chunks=[
                            RetrievedChunk(
                                chunk_id=str(c.chunk_id),
                                document_id=str(c.document_id) if c.document_id else None,
                                document_name=c.document_name,
                                page=c.page,
                                heading_path=c.heading_path,
                                source_type=c.source_type,
                                excerpt=c.text[:EXCERPT_CHARS],
                                vector_score=c.vector_score,
                                bm25_score=c.bm25_score,
                                fused_score=c.fused_score,
                                rerank_score=c.rerank_score,
                                dropped=False,
                            )
                            for c in fused
                        ],
                    )
                )
            return _fuse_multi_query(result_sets), events, provenance

        fused, retrieval_events, provenance = await _step(
            "retrieve", lambda: retrieve_queries(rewritten)
        )
        attempt_events = retrieval_events

        # Never more than one retry regardless of the runtime override —
        # answer-first (batch A) made a second retry a latency bug, not a
        # quality control.
        retry_limit = min(int(runtime_value("retrieval.retry_limit", MAX_SUFFICIENT_RETRIES)), 1)
        retries_left = retry_limit
        current_query = rewritten
        dropped: list[ScoredChunk] = []
        expanded_contexts: list[ExpandedContext] = []
        abstain_threshold = 0.0
        # One reranker for the whole run (KI-26, D2 item 4): the relevance
        # gate reads which engine answered from it after the loop's retries.
        reranker = get_reranker(engine, str(params.run_id))
        relevance_ok = True
        while True:
            reranked = await _step(
                "rerank",
                partial(
                    _rerank_candidates,
                    reranker,
                    query=current_query,
                    chunks=fused,
                    provenance=provenance,
                    limit=int(runtime_value("retrieval.top_k", RERANK_TOP_N)),
                ),
            )
            _add_rerank_scores(attempt_events, reranked)
            winners = dedupe_adjacent(reranked)
            # Sanitize after rerank (TRD §11 layer 4, amended for KI-11):
            # only the chunks that can reach the generator are asked about,
            # and a dropped chunk is not backfilled from beyond the reranked
            # set — generation simply sees fewer chunks.
            winners, sanitize_dropped, sanitize_answers = await _step(
                "sanitize",
                partial(sanitize_chunks, engine, run_id=str(params.run_id), chunks=winners),
            )
            for name, answer in sanitize_answers.items():
                decision_events.append(
                    Decision(
                        run_id=str(params.run_id),
                        name=name,
                        value=answer.value,
                        probability=answer.probability,
                        probabilities=answer.probabilities,
                        engine=answer.engine,
                        latency_ms=answer.latency_ms,
                        reasoning=answer.reasoning,
                    )
                )
            dropped.extend(sanitize_dropped)
            # KI-26 (D2 item 4): the second abstain signal. `sufficient`
            # can't separate answerable from unanswerable evidence (margin
            # -0.06 in both D1 acceptance runs), but the max rerank score of
            # the post-sanitize winners can — see `rerank_abstain` in
            # thresholds.py for the replay table. Gated only on scores
            # JevRerank answered: NVIDIA/Cohere use other scales, and fused
            # order's top score is always 1.0. An outage (no passage got a
            # real answer) skips the gate so it can never abstain.
            relevance_engine = (
                reranker.relevance_engine() if isinstance(reranker, JevRerank) else None
            )
            relevance_ok = True
            if relevance_engine is not None:
                scores = [c.rerank_score for c in winners if c.rerank_score is not None]
                if scores:
                    relevance_max = max(scores)
                    relevance_threshold = threshold("rerank_abstain", relevance_engine)
                    relevance_ok = relevance_max >= relevance_threshold
                    decision_events.append(
                        Decision(
                            run_id=str(params.run_id),
                            name="relevance",
                            value=relevance_max,
                            probability=None,
                            probabilities=None,
                            engine=relevance_engine,
                            latency_ms=0,
                            threshold=relevance_threshold,
                            reasoning=(
                                "max rerank score of the post-sanitize winners "
                                f"({len(scores)} scored passages)"
                            ),
                        )
                    )
            expanded_contexts = await expand_context(session, winners)
            top_for_check = expanded_contexts[
                : int(runtime_value("retrieval.top_k", TOP_CHUNKS_FOR_SUFFICIENT))
            ]
            sufficient_question = _sufficient_question(current_query, top_for_check)
            sufficient_answer = await _step(
                "sufficient",
                partial(
                    engine.decide,
                    state={"run_id": str(params.run_id), "kind": "sufficient"},
                    questions={"sufficient": sufficient_question},
                ),
            )
            sufficient = sufficient_answer["sufficient"]
            decision_events.append(
                Decision(
                    run_id=str(params.run_id),
                    name="sufficient",
                    value=sufficient.value,
                    probability=sufficient.probability,
                    probabilities=sufficient.probabilities,
                    engine=sufficient.engine,
                    latency_ms=sufficient.latency_ms,
                    reasoning=sufficient.reasoning,
                )
            )
            p_sufficient = float(sufficient.value)
            abstain_threshold = threshold("sufficient_abstain", sufficient.engine)
            # One bar: both signals must clear, with the same single retry.
            if p_sufficient >= abstain_threshold and relevance_ok:
                break
            if retries_left > 0:
                retries_left -= 1
                current_query = await rewrite_node.rewrite_query(
                    question=params.question,
                    history=history,
                    summary=summary,
                    small_model=params.small_model,
                    complete_fn=complete,
                )
                fused, retry_events, provenance = await _step(
                    "retrieve", partial(retrieve_queries, current_query)
                )
                retrieval_events.extend(retry_events)
                attempt_events = retry_events
                continue
            break

        kept = winners
        dropped_ids = {str(c.chunk_id) for c in dropped}
        for event in retrieval_events:
            for chunk in event.chunks:
                if chunk.chunk_id in dropped_ids:
                    chunk.dropped = True

        last_decision = decision_events[-1] if decision_events else None
        p_sufficient_final = (
            float(last_decision.value)
            if last_decision is not None and last_decision.name == "sufficient"
            else 0.0
        )
        abstain_event: Abstain | None = None
        conflict_event: Conflict | None = None
        # KI-25: an abstention carries no contexts and persists no citations;
        # what was found reaches the user as plain text in the abstain message.
        contexts: list[ExpandedContext] = []

        if p_sufficient_final < abstain_threshold or not relevance_ok:
            abstain_event = build_abstain_event(
                str(params.run_id), kept, offered_actions=["web", "deep"]
            )
            # `relevance` is emitted before `sufficient` in the loop, so the
            # last decision being `sufficient` still means the sufficiency
            # floor was met; an abstention here with p_sufficient_final above
            # the floor is the relevance gate (KI-26).
        else:
            contexts = expanded_contexts
            conflict_answer_map = await engine.decide(
                state={"run_id": str(params.run_id), "kind": "conflict"},
                questions={"conflict": _conflict_question(winners[:TOP_CHUNKS_FOR_SUFFICIENT])},
            )
            conflict_answer = conflict_answer_map["conflict"]
            decision_events.append(
                Decision(
                    run_id=str(params.run_id),
                    name="conflict",
                    value=conflict_answer.value,
                    probability=conflict_answer.probability,
                    probabilities=conflict_answer.probabilities,
                    engine=conflict_answer.engine,
                    latency_ms=conflict_answer.latency_ms,
                    reasoning=conflict_answer.reasoning,
                )
            )
            if float(conflict_answer.value) >= threshold(
                "conflict_disclose", conflict_answer.engine
            ):
                docs = {c.document_id or c.chunk_id for c in winners[:5]}
                doc_list = list(docs)
                midpoint = max(1, len(doc_list) // 2)
                conflict_event = Conflict(
                    run_id=str(params.run_id),
                    citation_ids_left=[str(d) for d in doc_list[:midpoint]],
                    citation_ids_right=[str(d) for d in doc_list[midpoint:]],
                    rule_applied=str(runtime_value("source_priority", "documents_first")),
                )

        history_tokens = sum(count_tokens(text) for _, text in history[-6:])
        contexts, context_used = trim_context(
            contexts,
            window_tokens=params.context_window,
            history_tokens=history_tokens,
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

    return AutoRun(
        params=params,
        history=history,
        contexts=contexts,
        kept_chunks=kept,
        dropped_chunks=dropped,
        rewritten=rewritten,
        retrieval_events=retrieval_events,
        decision_events=decision_events,
        conflict_event=conflict_event,
        abstain_event=abstain_event,
        latency_ms=latency_ms,
        context_used=context_used,
        ingress=ingress,
        sufficiency_p=p_sufficient_final,
    )


async def _stream_abstention(run: AutoRun) -> AsyncIterator[str]:
    if run.abstain_event is None:
        return
    async for token in stream_abstention(
        run.abstain_event,
        litellm_model=run.params.litellm_model,
        question=run.rewritten,
        metadata={"run_id": str(run.params.run_id), "user_id": str(run.params.user_id)},
    ):
        yield token


async def finalize_auto_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: AutoRun,
    *,
    generate_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Post-delivery: refresh the rolling summary if due."""
    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, run.params.chat_id)
        await rewrite_node.maybe_refresh_summary(
            session,
            chat_id=run.params.chat_id,
            summary=chat.summary if chat is not None else None,
            small_model=run.params.small_model,
            complete_fn=complete,
        )
