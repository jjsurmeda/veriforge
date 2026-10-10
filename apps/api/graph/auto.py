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
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from itertools import combinations
from typing import TypeVar
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
from retrieval.cache import get_query_embeddings
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
from schemas.decisions import Answer, Choice, Noul, Score
from schemas.events import (
    Abstain,
    Conflict,
    Decision,
    Retrieval,
    RetrievedChunk,
    StepCompleted,
    StepStarted,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

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

# Lane B item 5: when the evidence is clearly absent, the rewrite + retry is
# another 13-15 s to reach the same abstention, so it is skipped.
#
# The two bounds come from the recorded runs, not from taste. Offline replay of
# the dev database's decision events (2026-10-07): 636 Auto runs carry a
# sufficiency reading, 238 of them took the retry, and 231 of those still
# abstained.
#
#   | first attempt            | n   | sufficiency        | max rerank score |
#   | ------------------------ | --- | ------------------ | ---------------- |
#   | retry produced an answer |   7 | 0.01 - 0.43        | 0.47 - 0.75 (3 with a reading) |
#   | retry abstained anyway   | 231 | 0.01 - 0.63        | 0.00 - 0.97 (175 with a reading) |
#
# Sufficiency alone separates nothing (a rescued run scored 0.01), so the skip
# needs BOTH readings far below their floors, and a run with no relevance
# reading never skips:
#
#   * sufficiency <= 0.02 — the floor is 0.05 and the lowest sufficiency any
#     answering run recorded is 0.05, so this is below every answering run by
#     0.03; it catches 70 of the 231 futile retries.
#   * relevance <= 0.40 — the floor is 0.60, and the lowest relevance among
#     runs the retry rescued is 0.47, a margin of 0.07. Nothing in the skip
#     band scored above 0.10 on relevance in the replay.
#
# 0 of the 7 rescued answers fall inside the band. AD-4 makes both bounds
# admin-overridable (`retrieval.retry_skip_sufficient_max`,
# `retrieval.retry_skip_relevance_max`); a value of None disables the skip.
RETRY_SKIP_SUFFICIENT_MAX = 0.02
RETRY_SKIP_RELEVANCE_MAX = 0.40
# Only four recorded runs carry an entity reading (P2a is new), so this bound
# is deliberately inert: it exists to stop a MATCHED passage being called
# "clearly absent", and it never fires on its own.
RETRY_SKIP_ENTITY_MAX = 0.50

# KI-34: the conflict check asks one question per candidate PAIR of passages,
# batched into a single DecisionEngine call. With at most
# TOP_CHUNKS_FOR_SUFFICIENT sides there are 10 pairs, which is the cap: it
# bounds one call's prompt size without dropping a pair that could be the real
# conflict.
CONFLICT_MAX_PAIRS = 10

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
    # Lane B item 5: the rewrite + retry was skipped because every signal was
    # far below its floor. Carried on the run so a caller (and a test) can see
    # that a fast decline was a deliberate decision, not a short first pass.
    retry_skipped: bool = False

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


# Lane B item 6 (TRD §7.1: "skip query variants on simple single-hop lookups
# (complexity = single, intent = lookup)").
#
# OFF by default and meant to stay off until item 7 shows no recall loss on
# every set: the brief calls this the riskiest item in the lane, and the three
# variants are also what makes multi-query recall work on a phrasing the
# embedding misses. `retrieval.skip_variants_simple_lookup` is the admin
# override (AD-4).
SKIP_VARIANTS_SIMPLE_LOOKUP = False


def _skip_variants_for(ingress: IngressOutcome) -> bool:
    """Skip the query variants for a single-hop, single-entity lookup?

    Both conditions are needed. `complexity = single` alone still covers a
    multi-part question, whose parts are separate retrievals and not
    phrasings — dropping those is the KI-12 abstention. `intent = lookup`
    alone still covers a compare question, whose per-entity queries are the
    only reason the second book is retrieved at all.
    """
    if not bool(
        runtime_value(
            "retrieval.skip_variants_simple_lookup", SKIP_VARIANTS_SIMPLE_LOOKUP
        )
    ):
        return False
    return ingress.complexity == "single" and ingress.intent == "lookup"


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


# KI-54 (P2a item 4): the entity the question names, so a passage about a
# DIFFERENT product cannot answer it. Model codes (AW-2000, R-7, K9) and
# capitalised names ("Kestrel", "Ridgeline", "Montbriv"), conservatively:
# a wrong extraction costs one extra "no" the other passages can still
# offset, and an empty list skips the check — which never abstains.
_MODEL_CODE_RE = re.compile(r"\b[A-Z]{1,4}-?\d{1,4}(?:[-/]\d{1,4})*\b")
_CAPITALISED_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|the))*(?=\b)")
_ENTITY_STOP = {
    "Compare", "How", "What", "Why", "When", "Where", "Who", "Which", "Does",
    "Did", "Can", "Could", "Should", "Shall", "May", "Might", "The", "A", "An",
    "This", "That", "These", "Those", "There", "Here", "It", "I", "You", "We",
    "They", "He", "She", "My", "Your", "Our", "Their", "In", "On", "At", "For",
    "With", "From", "About", "Into", "Over", "Under", "Per", "Also", "Please",
    "Note", "Hi", "Hello", "Thanks", "Thank", "Yes", "No",
    # FR/DE/ES openers that the ASCII-range regex still matches
    "Quel", "Quels", "Qui", "Quand", "Comment", "Pourquoi",
    "Wer", "Was", "Wie", "Wann", "Wo", "Warum", "Welche", "Welcher", "Welches",
}


def named_entities(question: str) -> list[str]:
    """The entities a question names, conservatively (KI-54).

    Empty means "no named entity — skip the check". A name at the very
    start of the question is excluded: it may be a sentence opener, and
    the safe direction is to skip (skipping never abstains), not to guess.
    ponytail: the capitalised-name regex still misses ALL-CAPS titles and
    quoted names, and keeps a mid-question sentence opener ("Note: ...").
    """
    entities: list[str] = []
    for match in _MODEL_CODE_RE.finditer(question):
        entities.append(match.group(0))
    for match in _CAPITALISED_NAME_RE.finditer(question):
        entity = match.group(0)
        if entity.split(" ")[0] in _ENTITY_STOP:
            continue
        if match.start() == 0:
            continue
        entities.append(entity)
    return list(dict.fromkeys(entities))


def _entity_passage_questions(
    question: str, entities: list[str], top_contexts: list[ExpandedContext]
) -> dict[str, Noul]:
    """KI-54 (P2a item 4): one Noul per top-k passage, "is this passage
    about the entity the question names?", batched into the existing
    post-sanitize sufficiency call — no extra round trip. Skipped when the
    question names no entity or nothing survived to the top-k."""
    if not entities or not top_contexts:
        return {}
    entity_list = " and ".join(f"'{entity}'" for entity in entities)
    return {
        f"entity_{index}": Noul(
            prompt=(
                f"The question below names the entity or entities {entity_list}. "
                "Does this passage concern that same entity or entities — the "
                "same product or model family, the same organisation, or the "
                "same named place or person? Answer yes only if the passage is "
                "about the named entity; a passage about a different product, "
                "even in the same category, is not about it.\n\n"
                f"[question]\n{question}\n\n"
                f"[passage]\n{top_contexts[index].chunk.text[:1500]}"
            )
        )
        for index in range(len(top_contexts))
    }


def _evidence_clearly_absent(
    *,
    p_sufficient: float,
    relevance_max: float | None,
    relevance_measured: bool,
    entity_max: float | None,
    entity_measured: bool,
    entity_ok: bool,
) -> bool:
    """Is the evidence CLEARLY absent, so the rewrite + retry is pointless?

    Every signal must be far below its floor, and a signal that was not
    measured blocks the skip:

    * `relevance_measured` is required, not optional. The offline replay of the
      recorded runs (2026-10-07, 636 Auto runs with a sufficiency reading) is
      what the two bounds come from, and it says plainly that sufficiency alone
      cannot decide this: among the runs the retry RESCUED, sufficiency went as
      low as 0.01, and the three of those with a relevance reading sat at 0.47,
      0.64 and 0.75. The runs the retry did not rescue, with a relevance
      reading, sat at 0.40 or below for 119 of them at sufficiency <= 0.05, and
      at 0.10 or below for the 70 at sufficiency <= 0.02 — the band these two
      bounds describe. No run with a relevance reading in the skip band was
      rescued by a retry (0 of 7).
    * `entity_measured` alone is not enough to skip: only four recorded runs
      have an entity reading (it is new in P2a), so the check is used the other
      way round — if it ran and a passage MATCHED, the evidence is not clearly
      absent and the retry still happens.

    Both bounds are admin-overridable (AD-4): `retrieval.retry_skip_sufficient_max`
    and `retrieval.retry_skip_relevance_max`. The skip is a latency
    optimisation, so the failure direction is a decline that could have been an
    answer — the reason the bounds sit below the floors rather than at them.
    """
    if not relevance_measured or relevance_max is None:
        return False
    if entity_measured and entity_ok:
        return False
    entity_bound = runtime_value("retrieval.retry_skip_entity_max", RETRY_SKIP_ENTITY_MAX)
    if entity_max is not None and entity_bound is not None and entity_max > float(entity_bound):
        return False
    sufficient_bound = runtime_value(
        "retrieval.retry_skip_sufficient_max", RETRY_SKIP_SUFFICIENT_MAX
    )
    relevance_bound = runtime_value(
        "retrieval.retry_skip_relevance_max", RETRY_SKIP_RELEVANCE_MAX
    )
    # AD-4: an admin can turn the skip off by setting either bound to null.
    if sufficient_bound is None or relevance_bound is None:
        return False
    return (
        p_sufficient <= float(sufficient_bound)
        and relevance_max <= float(relevance_bound)
    )


async def _search_one_variant(
    session: AsyncSession,
    variant: str,
    *,
    embedding: list[float],
    params: AutoRunInput,
    ingress: IngressOutcome,
) -> list[ScoredChunk]:
    """One variant's hybrid search, with the ownership filter injected here
    (CLAUDE.md: every retrieval query gets its ownership filter server-side,
    and `params.client_filters` may only narrow it)."""
    ownership = Ownership(
        user_id=params.user_id,
        collection_ids=list(params.collection_ids),
        chat_id=params.chat_id,
    )
    return await hybrid_search(
        session,
        query_text=variant,
        query_embedding=embedding,
        ownership=ownership,
        filters=params.client_filters,
        lexical_weight=ingress.lexical_weight,
    )


async def _search_one_variant_on_own_session(
    session_factory: async_sessionmaker[AsyncSession],
    variant: str,
    *,
    embedding: list[float],
    params: AutoRunInput,
    ingress: IngressOutcome,
) -> list[ScoredChunk]:
    """One variant's search on its OWN session, so the fan-out can run
    concurrently (one AsyncSession cannot run two statements at once).

    Read-only, so it needs no explicit transaction: the `async with` rolls
    back on the way out and there is nothing to commit. The rest of
    `prepare_auto_run` keeps its single transaction.
    """
    async with session_factory() as session:
        return await _search_one_variant(
            session, variant, embedding=embedding, params=params, ingress=ingress
        )


def _sub_step_timer(
    publish: EventPublisher | None, *, node: str, run_id: UUID
) -> Callable[[str, Callable[[], Awaitable[T]]], Awaitable[T]]:
    """Like `make_step_timer`, but the duration is NOT added to `latency_ms`.

    CH-5 (progress, live): the sub-steps inside one outer step exist so the
    trace shows the work as it happens rather than after the fact. Their
    labels name the query being run, and `latency_ms` is published as the
    run's node metrics, so recording them there would put a query string
    into a metric key and add one entry per variant per run. The outer
    `retrieve` step still carries the total.
    """

    async def _sub_step(label: str, work: Callable[[], Awaitable[T]]) -> T:
        if publish is None:
            return await work()
        await publish(run_id, StepStarted(node=node, label=label))
        started = time.monotonic()
        try:
            result = await work()
        finally:
            duration = int((time.monotonic() - started) * 1000)
            await publish(run_id, StepCompleted(node=node, label=label, duration_ms=duration))
        return result

    return _sub_step


def _conflict_sides(winners: list[ScoredChunk]) -> list[ScoredChunk]:
    """The top passages eligible to be a conflict side: at most
    `TOP_CHUNKS_FOR_SUFFICIENT`, one per document.

    One per document because a conflict is a disagreement *between sources*.
    Two chunks of the same document are the same source, and pairing them
    would let the checker report a document disagreeing with itself.
    """
    sides: list[ScoredChunk] = []
    seen: set[object] = set()
    for chunk in winners:
        key = chunk.document_id or chunk.chunk_id
        if key in seen:
            continue
        seen.add(key)
        sides.append(chunk)
        if len(sides) >= TOP_CHUNKS_FOR_SUFFICIENT:
            break
    return sides


def _conflict_pair_questions(
    sides: list[ScoredChunk], question: str
) -> dict[str, Noul | Choice | Score]:
    """One DecisionEngine question per candidate pair of sides, batched into
    a single `decide` call (TRD §8 supports several questions per call).

    KI-34: the old single question asked "do ANY two of these chunks
    disagree?" and the code then split the document ids at the midpoint. The
    "sides" it published were therefore not the passages that disagreed — just
    a list cut in two, so the UI could show a conflict whose two sides agreed
    with each other (TR-5 promises "cites both sides"). A question per PAIR is
    what makes the answer attributable: the pair that fires names the two
    passages, and those two are the sides.

    At most `CONFLICT_MAX_PAIRS` pairs, so a long passage list cannot turn one
    call into an unbounded question set.
    """
    budget = SUFFICIENT_EVIDENCE_CHARS // max(1, len(sides) * (len(sides) - 1) // 2)
    questions: dict[str, Noul | Choice | Score] = {}
    for index, (left, right) in enumerate(combinations(sides, 2)):
        if index >= CONFLICT_MAX_PAIRS:
            break
        questions[f"conflict_{index}"] = Noul(
            prompt=(
                "Do these two passages assert INCOMPATIBLE values for the "
                "same fact — two different values, where a reader could not "
                "hold both? Say yes only for a direct factual contradiction "
                "on a fact the question depends on. Say no if they agree, if "
                "they are about different facts, or if one is merely more "
                "detailed than the other.\n\n"
                f"[question]\n{question}\n\n"
                f"[passage A — {left.document_name or left.source_type}]\n"
                f"{left.text[:budget]}\n\n"
                f"[passage B — {right.document_name or right.source_type}]\n"
                f"{right.text[:budget]}"
            )
        )
    return questions


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
    # CH-5: the same publisher, minus the latency accounting (see
    # `_sub_step_timer`), for the sub-steps inside one outer step.
    _variant_step = _sub_step_timer(publish, node="auto", run_id=params.run_id)

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

        async def _no_call() -> None:
            """A step that legitimately makes no call — a skipped retrieval, or
            a stage whose questions were batched into an earlier one. Timed and
            published like any other step, so it still appears in the trace."""
            return None

        canonical_greeting = greeting_canonical(params.question)
        if canonical_greeting is not None:
            await _step("Greeting fast path: skipped ingress", _no_call)
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
            await _step("Small talk: skipped retrieval", _no_call)
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
            await _step("Library: skipped retrieval", _no_call)
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
            # Its own transaction, committed before the fan-out below: those
            # searches run on their own sessions, and a session cannot see
            # another session's uncommitted rows — so web chunks this run
            # indexes inside the run's transaction would be invisible to every
            # one of them, and a `source=web` run would not retrieve its own
            # web results. Everything after this point keeps the run's single
            # transaction.
            async with session_factory() as web_session, web_session.begin():
                await ensure_web_chunks(
                    web_session,
                    query=params.question,
                    chat_id=params.chat_id,
                    optional=source_filter == "both",
                )

        async def retrieve_queries(
            query: str,
        ) -> tuple[list[ScoredChunk], list[Retrieval], dict[UUID, str]]:
            # Lane B item 6: a single-hop, single-entity lookup does not need
            # three extra phrasings — they are overhead on the exact question
            # that already retrieves well. The setting defaults to OFF, and
            # item 7 is what would turn it on; the variants path is unchanged
            # until then. (Compare and multi-part intents keep their per-entity
            # and per-part queries regardless: those are not phrasings, they
            # are different questions, and dropping them is the KI-12 bug.)
            skip_variants = _skip_variants_for(ingress)
            # CH-5: every step inside `retrieve` publishes its own label, so
            # the trace shows the work as it happens. Before this, the first
            # thing a client saw after `retrieve` started was the first search
            # finishing — the variants call and the embedding batch were a
            # silent gap inside the stage they belong to.
            variants = (
                [query]
                if skip_variants
                else await _variant_step(
                    "query variants",
                    partial(
                        _generate_query_variants,
                        query,
                        params.small_model,
                        complete,
                        MULTI_QUERY_VARIANTS,
                    ),
                )
            )
            parts: list[str] = []
            if ingress.intent == "multi-part":
                parts = await _variant_step(
                    "query parts",
                    partial(
                        _generate_query_variants,
                        query,
                        params.small_model,
                        complete,
                        MULTI_PART_VARIANTS,
                        instruction=MULTI_PARTS,
                    ),
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
            # TRD §7.1: one embedding call for every variant, and the
            # searches themselves in parallel. Each search runs on its OWN
            # session from the factory — one AsyncSession cannot run concurrent
            # statements, and the sequential fan-out was the other half of the
            # stage's cost. The ownership filter is built per search inside
            # `_search_one_variant`, so it is on every one of them (CLAUDE.md).
            embeddings = await _variant_step(
                f"embed queries ({len(variants)})",
                partial(get_query_embeddings, session, variants),
            )
            result_sets: list[list[ScoredChunk]] = await asyncio.gather(
                *(
                    # One published sub-step per variant, so the trace shows the
                    # multi-query fan-out as it runs rather than one opaque
                    # `retrieve` that appears only when it is already over.
                    _variant_step(
                        f"retrieve: {variant}",
                        partial(
                            _search_one_variant_on_own_session,
                            session_factory,
                            variant,
                            embedding=embedding,
                            params=params,
                            ingress=ingress,
                        ),
                    )
                    for variant, embedding in zip(variants, embeddings, strict=True)
                )
            )
            events: list[Retrieval] = []
            provenance: dict[UUID, str] = {}
            for variant, fused in zip(variants, result_sets, strict=True):
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
        # KI-54: per-passage entity gate; True when the check is skipped
        # (no named entity) or a passage matched the last iteration.
        entity_ok = True
        # Lane B item 5: set when the retry was skipped because every signal
        # was far below its floor; published as a `retry_skipped` decision.
        skipped_retry = False
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
            # Kept for item 5's skip test: `relevance_measured` says the gate
            # actually produced a number, which the skip REQUIRES (see
            # `_evidence_clearly_absent`).
            relevance_max: float | None = None
            relevance_measured = False
            if relevance_engine is not None:
                scores = [c.rerank_score for c in winners if c.rerank_score is not None]
                if scores:
                    relevance_max = max(scores)
                    relevance_measured = True
                    relevance_threshold = threshold("rerank_abstain", relevance_engine)
                    relevance_ok = relevance_max >= relevance_threshold
                    relevance_decision = Decision(
                        run_id=str(params.run_id),
                        name="relevance",
                        value=relevance_max,
                        probability=None,
                        probabilities=None,
                        engine=relevance_engine,
                        latency_ms=0,
                        stage="rerank",
                        threshold=relevance_threshold,
                        reasoning=(
                            "max rerank score of the post-sanitize winners "
                            f"({len(scores)} scored passages)"
                        ),
                    )
                    decision_events.append(relevance_decision)
            expanded_contexts = await expand_context(session, winners)
            top_for_check = expanded_contexts[
                : int(runtime_value("retrieval.top_k", TOP_CHUNKS_FOR_SUFFICIENT))
            ]
            sufficient_question = _sufficient_question(current_query, top_for_check)
            # KI-54 (P2a item 4): the per-passage entity Noul rides this
            # same post-sanitize call (TRD §7.1) — no sequential round trip.
            # Empty when the question names no entity: the check is skipped.
            entity_questions = _entity_passage_questions(
                current_query, named_entities(current_query), top_for_check
            )
            # TRD §7.1 / lane B item 4: the conflict pairs ride this call too —
            # but ONLY when the sanitizer dropped nothing. When it dropped
            # something, the kept set changed underneath the question, so the
            # pairs are re-asked over what survived, in their own call after
            # the loop. `sides` is therefore per-iteration state: the conflict
            # event is built from the LAST attempt's, which is the attempt the
            # answer is delivered from.
            batched_pairs = not sanitize_dropped
            sides = _conflict_sides(winners)
            pair_questions = (
                _conflict_pair_questions(sides, params.question) if batched_pairs else {}
            )
            sufficient_answer = await _step(
                "sufficient",
                partial(
                    engine.decide,
                    state={"run_id": str(params.run_id), "kind": "sufficient"},
                    questions={
                        "sufficient": sufficient_question,
                        **entity_questions,
                        **pair_questions,
                    },
                ),
            )
            # Kept so the post-loop branch does not ask again on the common path.
            batched_conflict_answers = {
                name: answer
                for name, answer in sufficient_answer.items()
                if name.startswith("conflict_")
            }
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
            entity_ok = True
            entity_max: float | None = None
            if entity_questions:
                # Every passage in the top-k is about a DIFFERENT entity when
                # none of the per-passage Nouls clears the floor.
                entity_threshold = threshold("entity_match", sufficient.engine)
                entity_values = [
                    float(sufficient_answer[name].value) for name in entity_questions
                ]
                entity_max = max(entity_values)
                entity_ok = any(value >= entity_threshold for value in entity_values)
            # One bar: every signal must clear, with the same single retry.
            if p_sufficient >= abstain_threshold and relevance_ok and entity_ok:
                break
            if retries_left > 0 and _evidence_clearly_absent(
                p_sufficient=p_sufficient,
                relevance_max=relevance_max,
                relevance_measured=relevance_measured,
                entity_max=entity_max,
                entity_measured=bool(entity_questions),
                entity_ok=entity_ok,
            ):
                # Every signal is far below its floor (see the constants), so
                # the rewrite + full re-retrieve would abstain again for
                # another 13-15 s. Recorded as a decision so the trace says why
                # this run declined without a retry.
                skipped_retry = True
                decision_events.append(
                    Decision(
                        run_id=str(params.run_id),
                        name="retry_skipped",
                        value=p_sufficient,
                        probability=p_sufficient,
                        probabilities=None,
                        engine=sufficient.engine,
                        latency_ms=0,
                        stage="sufficient",
                        threshold=RETRY_SKIP_SUFFICIENT_MAX,
                        reasoning=(
                            "sufficiency, relevance and the entity check were all "
                            f"far below their floors (relevance {relevance_max}); "
                            "the rewrite + retry would not change the outcome"
                        ),
                    )
                )
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

        if p_sufficient_final < abstain_threshold or not relevance_ok or not entity_ok:
            abstain_event = build_abstain_event(
                str(params.run_id), kept, offered_actions=["web", "deep"]
            )
            # `relevance` is emitted before `sufficient` in the loop, so the
            # last decision being `sufficient` still means the sufficiency
            # floor was met; an abstention here with p_sufficient_final above
            # the floor is the relevance gate (KI-26).
        else:
            contexts = expanded_contexts
            # KI-34: timed (it was an untimed `await` between two timed
            # steps, so its cost appeared in no latency figure), and asking
            # about PAIRS rather than the whole evidence set, so the two
            # passages that disagree are the two the event names.
            #
            # Lane B item 4: on the common path the pairs already rode the
            # post-sanitize call and this is the same `_step`, so the stage is
            # still timed — now at its true cost, which is assembling the event
            # rather than a second round trip. When the sanitizer dropped
            # something the pairs were NOT batched, and they are asked here,
            # over the kept set, exactly as before.
            conflict_answers: dict[str, Answer] = {}
            if batched_pairs:
                conflict_answers = batched_conflict_answers
                # Same label, same timer, now measuring what the stage really
                # costs: the event assembly, not a second round trip. Publishing
                # it keeps `conflict` in the trace and in latency_ms either way.
                await _step("conflict", _no_call)
            elif len(sides) >= 2:
                conflict_answers = await _step(
                    "conflict",
                    partial(
                        engine.decide,
                        state={"run_id": str(params.run_id), "kind": "conflict"},
                        questions=_conflict_pair_questions(sides, params.question),
                    ),
                )
            best: tuple[ScoredChunk, ScoredChunk, Answer] | None = None
            for index, (left, right) in enumerate(combinations(sides, 2)):
                pair_answer: Answer | None = conflict_answers.get(f"conflict_{index}")
                if pair_answer is None:
                    continue
                if float(pair_answer.value) > 0 and (
                    best is None or float(pair_answer.value) > float(best[2].value)
                ):
                    best = (left, right, pair_answer)
            if best is not None and float(best[2].value) >= threshold(
                "conflict_disclose", best[2].engine
            ):
                left, right, _ = best
                conflict_event = Conflict(
                    run_id=str(params.run_id),
                    citation_ids_left=[str(left.chunk_id)],
                    citation_ids_right=[str(right.chunk_id)],
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
        retry_skipped=skipped_retry,
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
