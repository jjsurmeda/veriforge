"""KI-34: conflict disclosure names the two passages that disagree.

Before this, the conflict branch asked one question ("do ANY two of these
chunks disagree?") and then split the document ids of the top 5 at the
midpoint, so `citation_ids_left` / `citation_ids_right` were a list cut in
two, not the two sides. The UI could therefore show a conflict whose sides
agreed with each other. The check now asks one question per PAIR, batched
into a single DecisionEngine call, and the sides are the pair that fired.

Jev is a fixture and the generator is a stub — no live model.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Collection, Document, Section
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import (
    CONFLICT_MAX_PAIRS,
    TOP_CHUNKS_FOR_SUFFICIENT,
    AutoRunInput,
    _conflict_pair_questions,
    _conflict_sides,
    prepare_auto_run,
)
from retrieval.filters import ClientFilters
from retrieval.hybrid import ScoredChunk
from schemas.decisions import Answer, Question
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import (
    add_chunk,
    make_collection,
    make_document,
    make_section,
    make_user,
    vec,
)

SCORE_NAMES = {"guard_injection", "guard_jailbreak", "guard_pii", "off_topic", "lexical_weight"}
CHOICE_ANSWERS = {
    "source": ("both", {"upload": 0.05, "web": 0.05, "both": 0.9}),
    "complexity": ("single", {"single": 0.9, "multi": 0.1}),
    "risk": ("low", {"low": 0.95, "high": 0.05}),
}

# The two documents disagree about the warranty; the third agrees with the
# first. Distinct values for the same fact, which is what a conflict is.
WARRANTY_24_MONTHS = "The AW-2000 warranty is 24 months from the date of purchase."
WARRANTY_12_MONTHS = "The AW-2000 warranty is 12 months from the date of purchase."
WARRANTY_24_AGAIN = "Warranty coverage runs for 24 months from purchase."


class _ConflictJev(_IngressJev):
    """Ingress as usual, `sufficient` high enough to reach the conflict
    branch, and one conflict answer per candidate pair.

    `conflicting` names the two documents whose pair the engine reports as a
    conflict; every other pair answers "no". A pair is identified by which of
    the two marker strings its prompt carries, so the fake reads the same
    evidence the real engine would.
    """

    def __init__(self, conflicting: tuple[str, str] | None) -> None:
        super().__init__("lookup")
        self._conflicting = conflicting
        self.pair_prompts: list[str] = []
        self.calls: list[dict[str, Question]] = []

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        if any(name.startswith("conflict_") for name in questions):
            self.calls.append(questions)
        answers: dict[str, Answer] = {}
        for name in questions:
            question = questions[name]
            if name.startswith("conflict_"):
                self.pair_prompts.append(question.prompt)
                value = self._pair_value(question.prompt)
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=value, probability=value
                )
            elif name == "sufficient":
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.9, probability=0.9)
            elif name in SCORE_NAMES:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            elif name in CHOICE_ANSWERS:
                choice_value, probabilities = CHOICE_ANSWERS[name]
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value=choice_value,
                    probability=probabilities[choice_value],
                    probabilities=probabilities,
                )
            else:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers

    def _pair_value(self, prompt: str) -> float:
        if self._conflicting is None:
            return 0.01
        first, second = self._conflicting
        return 0.95 if first in prompt and second in prompt else 0.01


class _PassThroughRerank:
    def __init__(self, *_args: object) -> None:
        pass

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        return [(i, 1.0 - i / 100) for i in range(min(top_n, len(documents)))]


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "conflict@test.dev")


def _scored(chunk: Chunk, document: Document, section: Section, index: int) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.name,
        section_id=section.id,
        ord=index,
        page=None,
        text=chunk.text,
        heading_path=section.heading_path,
        source_type="document",
        vector_score=1.0 - index * 0.01,
        bm25_score=None,
        fused_score=1.0 - index * 0.01,
    )


async def _corpus_with_warranty_documents(
    db: AsyncSession, user: Any
) -> list[ScoredChunk]:
    """Three documents, one chunk each: 24 months, 12 months, 24 months."""
    collection = await make_collection(db, user, "warranties")
    chunks: list[ScoredChunk] = []
    for index, (name, text) in enumerate(
        [
            ("warranty_2025.md", WARRANTY_24_MONTHS),
            ("warranty_legacy.md", WARRANTY_12_MONTHS),
            ("returns.md", WARRANTY_24_AGAIN),
        ]
    ):
        document = await make_document(db, collection, name=name)
        section = await make_section(db, document)
        chunk = await add_chunk(
            db, document=document, section=section, ord=0, text_=text, embedding=vec(index + 2)
        )
        chunks.append(_scored(chunk, document, section, index))
    await db.commit()
    return chunks


async def _params(db: AsyncSession, chat: Any, user: Any, message_id: UUID) -> AutoRunInput:
    # _seed_chat creates a "docs" collection too, so select by name rather
    # than taking the user's only collection.
    collection_id = (
        await db.execute(
            select(Collection.id).where(
                Collection.owner_id == user.id, Collection.name == "warranties"
            )
        )
    ).scalar_one()
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="auto",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch, chunks: list[ScoredChunk], no_llm: dict[str, list[str]]
) -> None:
    async def fake_search(*args: Any, **kwargs: Any) -> list[ScoredChunk]:
        no_llm["retrieval"].append(str(kwargs.get("query_text", "")))
        return list(chunks)

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    monkeypatch.setattr(auto_module, "complete", _fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)


async def _fake_complete(**kwargs: Any) -> str:
    return "the question, standalone"


async def test_two_passages_with_different_values_land_on_opposite_sides(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """KI-34's stated test. The 24-month and 12-month passages disagree about
    the warranty, so they are the two sides — not a midpoint split of three
    document ids, which would have put two of the three on one side."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus_with_warranty_documents(db, user_a)
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _ConflictJev(("Warranty coverage runs for 24 months", "warranty is 12 months"))
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.conflict_event is not None
    texts = {str(c.chunk_id): c.text for c in chunks}
    # exactly the disagreeing pair, one on each side; the third document
    # (which agrees with the first) is on neither
    assert [texts[i] for i in run.conflict_event.citation_ids_left] == [WARRANTY_12_MONTHS]
    assert [texts[i] for i in run.conflict_event.citation_ids_right] == [WARRANTY_24_AGAIN]


async def test_agreeing_passages_produce_no_conflict(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The complement: with nothing disagreeing there is no event, even
    though the retrieval and the sufficiency gate both passed."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus_with_warranty_documents(db, user_a)
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _ConflictJev(None)
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is None, "the run must reach the conflict branch"
    assert run.conflict_event is None


async def test_the_conflict_call_is_one_batched_decide_and_is_timed(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """KI-34's second half: the call was outside `_step`, so it appeared in
    no latency figure. It is also one call for every pair, not one per pair
    (TRD §8 batches, and ingress already relies on it).

    Lane B item 4 changed WHERE that call is: the pairs now ride the
    post-sanitize sufficiency call (the sanitizer dropped nothing here), so the
    run makes one Jev round trip after ingress instead of two. The stage is
    still timed — see tests/graph/test_batched_conflict.py for the pair of
    cases (batched vs re-asked) side by side."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus_with_warranty_documents(db, user_a)
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _ConflictJev(("Warranty coverage runs for 24 months", "warranty is 12 months"))
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert len(jev.calls) == 1, "the pairs ride the one post-sanitize call"
    pairs = [name for name in jev.calls[0] if name.startswith("conflict_")]
    assert len(pairs) == 3, "3 passages -> 3 candidate pairs"
    assert "sufficient" in jev.calls[0], "the same call, not one of its own"
    assert "conflict" in run.latency_ms


def test_each_pair_gets_its_own_question_naming_both_passages() -> None:
    """The attribution, stated on the question itself: a question about the
    whole evidence set cannot say WHICH two disagree, which is the whole of
    KI-34."""
    sides = [
        ScoredChunk(
            chunk_id=UUID(int=1),
            document_id=UUID(int=101),
            document_name="warranty_2025.md",
            section_id=None,
            ord=0,
            page=None,
            text=WARRANTY_24_MONTHS,
            heading_path=None,
            source_type="document",
            vector_score=None,
            bm25_score=None,
            fused_score=0.0,
        ),
        ScoredChunk(
            chunk_id=UUID(int=2),
            document_id=UUID(int=102),
            document_name="warranty_legacy.md",
            section_id=None,
            ord=0,
            page=None,
            text=WARRANTY_12_MONTHS,
            heading_path=None,
            source_type="document",
            vector_score=None,
            bm25_score=None,
            fused_score=0.0,
        ),
    ]

    questions = _conflict_pair_questions(sides, "How long is the warranty?")

    assert list(questions) == ["conflict_0"]
    prompt = questions["conflict_0"].prompt
    assert WARRANTY_24_MONTHS in prompt
    assert WARRANTY_12_MONTHS in prompt
    assert "warranty_2025.md" in prompt and "warranty_legacy.md" in prompt
    assert "How long is the warranty?" in prompt
    assert "INCOMPATIBLE" in prompt


def test_one_side_per_document_so_a_document_cannot_disagree_with_itself() -> None:
    chunks = [
        ScoredChunk(
            chunk_id=UUID(int=i + 1),
            document_id=UUID(int=(i // 2) + 101),  # two chunks share each document
            document_name=f"doc-{i // 2}.md",
            section_id=None,
            ord=i,
            page=None,
            text=f"passage {i}",
            heading_path=None,
            source_type="document",
            vector_score=None,
            bm25_score=None,
            fused_score=0.0,
        )
        for i in range(6)
    ]

    sides = _conflict_sides(chunks)

    assert [chunk.chunk_id for chunk in sides] == [UUID(int=1), UUID(int=3), UUID(int=5)]
    assert len({chunk.document_id for chunk in sides}) == len(sides)


def test_the_pair_count_is_capped() -> None:
    """Bounded prompt: the cap holds even past the passage limit, so a future
    change to TOP_CHUNKS_FOR_SUFFICIENT cannot silently multiply the
    question set."""
    sides = [
        ScoredChunk(
            chunk_id=UUID(int=i + 1),
            document_id=UUID(int=i + 101),
            document_name=f"doc-{i}.md",
            section_id=None,
            ord=i,
            page=None,
            text=f"passage {i}",
            heading_path=None,
            source_type="document",
            vector_score=None,
            bm25_score=None,
            fused_score=0.0,
        )
        for i in range(TOP_CHUNKS_FOR_SUFFICIENT + 4)
    ]

    questions = _conflict_pair_questions(sides, "?")

    # _conflict_sides caps the sides first, so the pairs are exactly the cap
    capped = _conflict_sides(sides)
    assert len(questions) == min(CONFLICT_MAX_PAIRS, len(capped) * (len(capped) - 1) // 2)
    assert len(questions) <= CONFLICT_MAX_PAIRS
