"""The state a run carries between stages, and the environment it runs in.

Two objects, both explicit:

* `AutoRunState` — everything a stage produces and a later stage reads:
  history, the ingress outcome, the rewritten query, the events, the
  contexts, the verdict. A stage takes it and returns it.
* `StageEnv` — the things that are not run state: the session, the decision
  engine, the step timers and `StageSeams`.

`StageSeams` is the external functions the stages call. `graph/auto.py`
binds it from its own module namespace, so a test replaces one seam at that
module boundary and every stage sees the replacement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decisions import DecisionEngine
from graph.ingress import IngressOutcome
from graph.rewrite import CompleteFn
from graph.stages.generate_stage import stream_answer
from graph.timing import EventPublisher
from retrieval.expand import ExpandedContext
from retrieval.filters import ClientFilters
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import RerankProvider
from schemas.events import Abstain, Conflict, Decision, Retrieval

T = TypeVar("T")

StepFn = Callable[[str, Callable[[], Awaitable[T]]], Awaitable[T]]


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
    seams: StageSeams
    chitchat: bool = False
    sufficiency_p: float = 0.0
    library_names: list[str] | None = None
    # Set when the rewrite + retry was skipped because every signal was far
    # below its floor, so a caller (and a test) can see that a fast decline
    # was a deliberate decision, not a short first pass.
    retry_skipped: bool = False

    async def stream_answer(self) -> AsyncIterator[str]:
        async for token in stream_answer(self):
            yield token


@dataclass
class AutoRunState:
    """What the stages hand to each other, in the order they produce it."""

    history: list[tuple[str, str]]
    summary: str | None
    has_collections: bool
    ingress: IngressOutcome
    rewritten: str
    chitchat: bool = False
    # The classifier's `chitchat` verdict with its off-topic guard applied.
    # With sources in scope the run retrieves anyway and the evidence decides
    # between a grounded answer and this chitchat reply; with none in scope
    # the fast reply is the whole answer.
    chitchat_route: bool = False
    library_names: list[str] | None = None
    contexts: list[ExpandedContext] = field(default_factory=list)
    kept_chunks: list[ScoredChunk] = field(default_factory=list)
    dropped_chunks: list[ScoredChunk] = field(default_factory=list)
    retrieval_events: list[Retrieval] = field(default_factory=list)
    decision_events: list[Decision] = field(default_factory=list)
    conflict_event: Conflict | None = None
    abstain_event: Abstain | None = None
    sufficiency_p: float = 0.0
    retry_skipped: bool = False
    context_used: int = 0


@dataclass(frozen=True)
class StageSeams:
    """The external functions the stages call, bound in `graph/auto.py`."""

    complete: CompleteFn
    hybrid_search: Callable[..., Awaitable[list[ScoredChunk]]]
    get_reranker: Callable[..., RerankProvider]
    rerank_candidates: Callable[..., Awaitable[list[ScoredChunk]]]
    runtime_value: Callable[[str, Any], Any]
    stream_grounded_answer: Callable[..., AsyncIterator[str]]
    stream_chitchat_reply: Callable[..., AsyncIterator[str]]
    stream_library_reply: Callable[..., AsyncIterator[str]]


@dataclass(frozen=True)
class StageEnv:
    params: AutoRunInput
    session: AsyncSession
    session_factory: async_sessionmaker[AsyncSession]
    engine: DecisionEngine
    seams: StageSeams
    step: StepFn[Any]
    variant_step: StepFn[Any]
    publish: EventPublisher | None
    latency_ms: dict[str, int]
