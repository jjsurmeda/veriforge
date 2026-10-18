"""Cohere / NVIDIA rerank behind a provider interface (TRD §9.2: top 40 → top 8).

No SDK — httpx is already a dependency. Without COHERE_API_KEY or
NVIDIA_API_KEY the fused order passes through unchanged (local dev), which
the fused_score doubles as the rerank score. Rerank results are never
cached (TRD §9.4).
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from config import Settings, get_settings
from decisions.engine import DecisionEngine, DecisionUnavailable
from decisions.thresholds import RerankerUncalibrated, reranker_calibrated
from errors import AppError
from retrieval.context import count_tokens
from retrieval.hybrid import ScoredChunk
from runtime import runtime_value
from schemas.decisions import Answer, Choice, Question

logger = logging.getLogger(__name__)

RERANK_TOP_N = 8

RerankResult = list[tuple[int, float]]


class RerankProvider(Protocol):
    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        """Return (document index, relevance score) pairs, best first."""
        ...


class CohereRerank:
    reranker_id = "cohere"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        async def call(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                "https://api.cohere.com/v2/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                },
            )

        if self._client is not None:
            response = await call(self._client)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await call(client)
        # One short retry for a per-minute 429. A trial key's monthly cap also
        # answers 429, and waiting on it only delays apply_rerank's fused-order
        # fallback, so the wait is capped rather than honouring retry-after.
        if response.status_code == 429:
            await asyncio.sleep(min(float(response.headers.get("retry-after", 2)), 2.0))
            if self._client is not None:
                response = await call(self._client)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await call(client)
        response.raise_for_status()
        results = response.json()["results"]
        pairs = [(int(r["index"]), float(r["relevance_score"])) for r in results]
        # Ties break by input (fused) order, whatever order the API returned.
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return pairs


class NvidiaRerank:
    """NVIDIA NIM reranking (ai.api.nvidia.com, model-in-path URL).

    The endpoint has no top_n parameter and does not guarantee ordering, so
    results are sorted by logit and sliced here.
    """

    reranker_id = "nvidia"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        async def call(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                f"https://ai.api.nvidia.com/v1/retrieval/{self._model}/reranking",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "query": {"text": query},
                    "passages": [{"text": d} for d in documents],
                    "truncate": "END",
                },
            )

        if self._client is not None:
            response = await call(self._client)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await call(client)
        # Same capped single retry as CohereRerank for per-minute 429s; the
        # fused-order fallback in apply_rerank covers persistent failures.
        if response.status_code == 429:
            await asyncio.sleep(2.0)
            if self._client is not None:
                response = await call(self._client)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await call(client)
        response.raise_for_status()
        rankings = response.json()["rankings"]
        pairs = sorted(
            ((int(r["index"]), float(r["logit"])) for r in rankings),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return pairs[:top_n]


class FusedOrderRerank:
    """Local fallback: identity ranking over the fused order (score = fused)."""

    reranker_id = "fused"

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        return [(i, 1.0 / (1 + i)) for i in range(min(top_n, len(documents)))]


# Jev's state limit, the same budget the Reviewer's batches use (TRD §10).
JEV_BATCH_TOKEN_BUDGET = 28_000
# Per-passage cap, mirroring review.py's _CHUNK_CAP: a pathological chunk
# must not eat a whole batch.
_PASSAGE_CHARS = 2_000


# The answer-containment rubric (TRD §9.6, `docs/conventions/rag-reference.md`
# "Rerank").
#
# The question this replaces asked how *relevant* a passage was and wanted a
# 0-1 number. That is a lexical-overlap judgement wearing a confidence
# costume, and KI-70 measured what it costs: on a gist question it scored the
# correct passages 0.35-0.36 while the entity check scored the *same* passages
# 0.95-0.97. A passage can be perfectly on-topic and still answer nothing —
# that is the normal state of the third-best chunk in a fan-out — so a
# relevance score is asked to carry a distinction it cannot see.
#
# The rubric asks the question the reranker is actually for: does this passage
# CONTAIN the information needed to answer or verify. Four levels, in the
# jev-rerank-bench order, graded as a `Choice` so the grader returns a
# distribution over them rather than a bare label.
ANSWER_LEVELS: tuple[str, ...] = (
    "off-topic",
    "related but does not answer the question",
    "partly answers the question",
    "fully answers the question",
)
# The value each level contributes to the passage's expected level, so a
# graded distribution ranks by its mean rather than by its argmax. Index 0 is
# off-topic and index 3 fully answers; the expectation is then divided by
# (len-1) to land back in 0-1, which is the range `ScoredChunk.rerank_score`,
# the citation row and the trace all already speak.
ANSWER_LEVEL_VALUE: dict[str, float] = {
    "off-topic": 0.0,
    "related but does not answer the question": 1 / 3,
    "partly answers the question": 2 / 3,
    "fully answers the question": 1.0,
}


def answer_containment_question(query: str, passage: str) -> Choice:
    """The TRD §9.6 rerank question, graded on the four answer levels."""
    return Choice(
        prompt=(
            "Does the passage contain the information needed to answer or "
            "verify the question?\n\n"
            f"[Question]\n{query}\n\n[Passage]\n{passage}"
        ),
        options=list(ANSWER_LEVELS),
        criteria=(
            "Choose the highest level the passage reaches. A passage is "
            "'off-topic' if it is about something else; 'related but does not "
            "answer' if it is on the subject but states none of the "
            "information the question asks for; 'partly answers' if it "
            "contains some of what is needed; 'fully answers' if the question "
            "can be answered from it alone."
        ),
    )


def answer_containment_score(answer: Answer | None) -> float:
    """A passage's score under the rubric: its EXPECTED level, normalised to
    0-1.

    Ranked by the expectation rather than by the chosen label because the
    grader returns a distribution: a passage graded 60/40 across "partly" and
    "fully" is more useful evidence than one graded 51/49 the other way, and
    the argmax throws that away into a tie. The same distribution is why this
    is a mean and not a count of levels.

    Degrades to the chosen level's own value when no distribution came back
    (the LLM fallback engine, or a grader that answered with a bare label), and
    to 0.0 when nothing came back at all — the run must not fail on one
    unanswered passage, which is the contract `JevRerank` has always had.
    """
    if answer is None:
        return 0.0
    probabilities = answer.probabilities or {}
    if probabilities:
        expected = sum(
            ANSWER_LEVEL_VALUE.get(level, 0.0) * probability
            for level, probability in probabilities.items()
        )
        total = sum(probabilities.values())
        if total > 0:
            return min(max(expected / total, 0.0), 1.0)
    return ANSWER_LEVEL_VALUE.get(str(answer.value), 0.0)


def batch_passages(query: str, documents: list[str]) -> list[list[int]]:
    """Split passages into batches whose question text fits one Jev call
    (<28K tokens). Returns the document indices per batch.

    Measured against the question that is actually sent, so the budget cannot
    drift from the prompt if the rubric is reworded.
    """
    batches: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for i, document in enumerate(documents):
        tokens = count_tokens(answer_containment_question(query, document[:_PASSAGE_CHARS]).prompt)
        if current and current_tokens + tokens > JEV_BATCH_TOKEN_BUDGET:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(i)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


class JevRerank:
    """Rerank by asking Jev one batched answer-containment question per
    candidate passage, graded on the four levels in `ANSWER_LEVELS` (TRD §9.6).

    Goes through DecisionEngine like every other decision (CLAUDE.md), so it
    inherits the breaker and the LLM fallback. A passage Jev fails to answer
    scores 0.0 rather than dropping the run, and `apply_rerank` still catches
    transport errors and falls back to fused order.
    """

    reranker_id = "jev"

    def __init__(self, engine: DecisionEngine, run_id: str) -> None:
        self._engine = engine
        self._run_id = run_id
        # Which engines actually answered. Not a gate any more — the relevance
        # floor that keyed off it is gone (ADR-006, R2a item 4) — but it is how
        # the trace and the ops log report that a reranker outage degraded the
        # order to fused order without failing the run, which is the difference
        # between a degraded run and a mystery.
        self.answered_by: set[str] = set()

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        pairs: list[tuple[int, float]] = []
        for batch in batch_passages(query, documents):
            questions: dict[str, Question] = {
                f"passage_{i}": answer_containment_question(query, documents[i][:_PASSAGE_CHARS])
                for i in batch
            }
            answers = await self._engine.decide(
                state={"run_id": self._run_id, "kind": "rerank"}, questions=questions
            )
            for i in batch:
                answer = answers.get(f"passage_{i}")
                if answer is not None:
                    self.answered_by.add(answer.engine)
                pairs.append((i, answer_containment_score(answer)))
        # Ranked by expected level, not by argmax (see ANSWER_LEVELS). Ties are
        # broken by the fused order the chunks arrived in, which `sort` already
        # gives us: `pairs` is built in document order and Python's sort is
        # stable.
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs[:top_n]


class RerankerUnavailable(AppError):
    status_code = 422

    def __init__(self, reranker_id: str, why: str) -> None:
        super().__init__(
            "reranker_unavailable",
            f"reranker {reranker_id!r} is unavailable: {why}",
            {"reranker": reranker_id},
        )


@dataclass(frozen=True)
class RerankerInfo:
    """One selectable reranker. `kind` says whether it is a decision model
    (goes through DecisionEngine, no key of its own) or a traditional
    cross-encoder behind an HTTP API."""

    id: str
    label: str
    kind: Literal["decision-model", "traditional"]
    # Rough USD per 1,000 queries of one 40-passage rerank; None = not a flat
    # price (Jev is metered by tokens: `scripts/compare_rerankers.py` measures
    # it from OpenRouter generation stats).
    cost_per_1k_queries_usd: float | None
    cost_note: str
    key_present: Callable[[Settings], bool]
    build: Callable[[Settings, DecisionEngine | None, str], RerankProvider | None]


def _build_jev(_: Settings, engine: DecisionEngine | None, run_id: str) -> RerankProvider | None:
    return JevRerank(engine, run_id) if engine is not None else None


# ponytail: one dict, no plugin discovery; a new reranker is one entry here plus
# its gate values in decisions/thresholds.py once calibrated.
RERANKERS: dict[str, RerankerInfo] = {
    info.id: info
    for info in (
        RerankerInfo(
            "jev",
            "Jev answer-containment rubric",
            "decision-model",
            None,
            "token-metered through the decision layer",
            lambda s: True,
            _build_jev,
        ),
        RerankerInfo(
            "cohere",
            "Cohere Rerank",
            "traditional",
            2.0,
            "Cohere list price, per 1,000 searches",
            lambda s: bool(s.cohere_api_key),
            lambda s, e, r: CohereRerank(s.cohere_api_key, s.cohere_rerank_model),
        ),
        RerankerInfo(
            "nvidia",
            "NVIDIA NIM rerank",
            "traditional",
            0.0,
            "hosted evaluation endpoint, free; self-hosting cost not included",
            lambda s: bool(s.nvidia_api_key),
            lambda s, e, r: NvidiaRerank(s.nvidia_api_key, s.nvidia_rerank_model),
        ),
        RerankerInfo(
            "fused",
            "Fused order (no rerank)",
            "traditional",
            0.0,
            "no model call",
            lambda s: True,
            lambda s, e, r: FusedOrderRerank(),
        ),
    )
}


def check_reranker(reranker_id: str) -> RerankerInfo:
    """Admit a reranker id for a run or refuse it by name. Never falls back."""
    info = RERANKERS.get(reranker_id)
    if info is None:
        raise RerankerUnavailable(reranker_id, "unknown id")
    if not info.key_present(get_settings()):
        raise RerankerUnavailable(reranker_id, "its API key is not configured")
    if not reranker_calibrated(reranker_id):
        raise RerankerUncalibrated(reranker_id)
    return info


def get_reranker(engine: DecisionEngine | None = None, run_id: str = "") -> RerankProvider:
    if not bool(runtime_value("retrieval.rerank", True)):
        return FusedOrderRerank()
    reranker_id = str(runtime_value("retrieval.reranker", "jev"))
    settings = get_settings()
    info = RERANKERS.get(reranker_id)
    if info is None:
        raise RerankerUnavailable(reranker_id, "unknown id")
    provider = info.build(settings, engine, run_id)
    if provider is not None:
        if not info.key_present(settings):
            raise RerankerUnavailable(reranker_id, "its API key is not configured")
        return provider
    # Jev selected but no engine: Fast mode has no DecisionEngine, so it cannot
    # ask Jev. Fast has no evidence gate, so ordering by a provider reranker is
    # safe there; fall through rather than dropping to fused order.
    logger.warning("retrieval.reranker=jev but no engine; using provider reranker")
    if settings.cohere_api_key:
        return CohereRerank(settings.cohere_api_key, settings.cohere_rerank_model)
    if settings.nvidia_api_key:
        return NvidiaRerank(settings.nvidia_api_key, settings.nvidia_rerank_model)
    return FusedOrderRerank()


async def apply_rerank(
    provider: RerankProvider,
    *,
    query: str,
    chunks: list[ScoredChunk],
    top_n: int = RERANK_TOP_N,
) -> list[ScoredChunk]:
    """top 40 fused → provider rerank → top n, rerank_score attached (§9.2)."""
    if not chunks:
        return []
    if not bool(runtime_value("retrieval.rerank", True)):
        return chunks[: int(runtime_value("retrieval.top_k", top_n))]
    if top_n == RERANK_TOP_N:
        top_n = int(runtime_value("retrieval.top_k", top_n))
    try:
        ranked = await provider.rerank(query=query, documents=[c.text for c in chunks], top_n=top_n)
    except (httpx.HTTPError, DecisionUnavailable) as exc:
        # A rerank outage degrades retrieval to fused order; it never fails the run.
        #
        # Both failure classes are here, and the second one was missing until
        # phase 1d item 1. An HTTP provider raises `httpx.HTTPError`, but the
        # default provider is `JevRerank`, which goes through DecisionEngine:
        # when Jev *and* the LLM fallback are both unreachable, the engine
        # raises `DecisionUnavailable`, an `AppError`. Catching only
        # `httpx.HTTPError` meant the handler the contract above is written
        # against did not cover the provider that actually runs — so one
        # transient decision-layer outage during rerank failed a whole item,
        # which is what made "passes twice" fail at random.
        logger.warning("rerank failed (%s); using fused order", exc)
        ranked = await FusedOrderRerank().rerank(
            query=query, documents=[c.text for c in chunks], top_n=top_n
        )
    return [chunks[index].with_rerank(score) for index, score in ranked]
