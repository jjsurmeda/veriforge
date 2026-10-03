"""KI-54 (P2a item 4): the entity gate.

A question naming entity A must not be answered from passages about entity
B with B's citations. The gate is a per-passage Noul — "is this passage
about the entity the question names?" — batched into the existing
post-sanitize sufficiency decide call (no new round trip). The run abstains
only when NO top-k passage matches the entity; a question that names no
entity skips the check entirely (the safe direction: skipping never
abstains). Auto's sufficiency/relevance gates stay as they are (D2).

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
from decisions.thresholds import threshold
from graph import auto as auto_module
from graph.auto import AutoRunInput, named_entities, prepare_auto_run
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

AW2000_BATTERY = "The AW-2000 battery lasts 10 hours on a full charge."
AW2000_WARRANTY = "The AW-2000 warranty is 24 months from the date of purchase."
AW2000_PORT = "The AW-2000 supports up to 8 Gbps on port 1."
KESTREL_BATTERY = "The Kestrel K9 battery lasts 38 hours on a full charge."


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What ingress protection rating does every Kestrel model carry?", ["Kestrel"]),
        ("How long does a flat-to-full charge take on the Kestrel K9?", ["K9", "Kestrel"]),
        (
            "What is the maximum line speed for the 27.5 t axle load class on the Ridgeline R-7?",
            ["R-7", "Ridgeline"],
        ),
        ("How long is the warranty on the AW-2000?", ["AW-2000"]),
        ("¿Cuánto tiempo debe cargarse el AW-2000 antes del primer uso?", ["AW-2000"]),
        ("Wie viele Geräte können gleichzeitig mit einem AW-2000 gekoppelt werden?", ["AW-2000"]),
        # No named entity -> empty list -> the check is skipped.
        ("How long does the battery last on a full charge?", []),
        ("What does the package contain?", []),
    ],
)
def test_named_entities(question: str, expected: list[str]) -> None:
    assert named_entities(question) == expected


class _EntityJev(_IngressJev):
    """Ingress as usual, `sufficient` high, and one entity answer per
    passage: yes iff the passage carries a marker in `matching`, which
    plays the judge's "is this passage about the entity?" call on the
    same text the real engine would read."""

    def __init__(self, matching: list[str], *, yes: float = 0.9, no: float = 0.05) -> None:
        super().__init__("lookup")
        self._matching = matching
        self._yes = yes
        self._no = no
        self.sufficient_calls: list[dict[str, Question]] = []

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        if "sufficient" in questions:
            self.sufficient_calls.append(dict(questions))
        answers: dict[str, Answer] = {}
        for name in questions:
            question = questions[name]
            if name.startswith("entity_"):
                # Judge the passage only: the question (and the entity it
                # names) is in every prompt, so matching against the whole
                # prompt would say "yes" for every passage.
                passage = question.prompt.split("[passage]", 1)[1]
                entity_value = self._yes if any(m in passage for m in self._matching) else self._no
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=entity_value, probability=entity_value
                )
            elif name == "sufficient":
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.9, probability=0.9)
            elif name in SCORE_NAMES:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            elif name in CHOICE_ANSWERS:
                value, probabilities = CHOICE_ANSWERS[name]
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value=value,
                    probability=probabilities[value],
                    probabilities=probabilities,
                )
            else:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers


class _PassThroughRerank:
    def __init__(self, *_args: object) -> None:
        pass

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        return [(i, 1.0 - i / 100) for i in range(min(top_n, len(documents)))]


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "entity@test.dev")


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


async def _corpus(db: AsyncSession, user: Any, texts: list[str]) -> list[ScoredChunk]:
    collection = await make_collection(db, user, "entity-corpus")
    chunks: list[ScoredChunk] = []
    for index, text in enumerate(texts):
        document = await make_document(db, collection, name=f"doc_{index}.md")
        section = await make_section(db, document)
        chunk = await add_chunk(
            db, document=document, section=section, ord=0, text_=text, embedding=vec(index + 2)
        )
        chunks.append(_scored(chunk, document, section, index))
    await db.commit()
    return chunks


async def _params(
    db: AsyncSession, chat: Any, user: Any, message_id: UUID, question: str
) -> AutoRunInput:
    collection_id = (
        await db.execute(
            select(Collection.id).where(
                Collection.owner_id == user.id, Collection.name == "entity-corpus"
            )
        )
    ).scalar_one()
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question=question,
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

    async def fake_complete(**kwargs: Any) -> str:
        # Echo the question verbatim: the rewrite keeps the entity names
        # (test_conflict's fixed-string stub would strip them) and the
        # variant parser yields the question as its single variant.
        return str(kwargs["messages"][-1]["content"])

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)


async def test_kestrel_question_with_aw2000_passages_abstains(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The KI-54 shape: sufficient passes (passages exist), relevance is
    fine, but every passage is about the AW-2000 while the question names
    the Kestrel — no passage matches, so the run abstains instead of
    substituting with citations."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY, AW2000_WARRANTY, AW2000_PORT])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=[])
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(
            db,
            chat,
            user_a,
            message_id,
            "What ingress protection rating does every Kestrel model carry?",
        ),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is not None
    assert run.contexts == []


async def test_aw2000_question_with_aw2000_passages_answers(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY, AW2000_WARRANTY, AW2000_PORT])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=["AW-2000"])
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id, "How long is the warranty on the AW-2000?"),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is None
    assert len(run.contexts) == 3
    # It passed the first bar: one sufficiency call, no rewrite + retry.
    assert len(jev.sufficient_calls) == 1


async def test_one_matching_passage_keeps_the_run(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any single matching passage is enough: the gate abstains only when
    NO passage matches the entity."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY, KESTREL_BATTERY, AW2000_PORT])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=["Kestrel K9"])
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(
            db,
            chat,
            user_a,
            message_id,
            "How long does a flat-to-full charge take on the Kestrel K9?",
        ),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is None
    assert len(run.contexts) == 3


async def test_question_without_named_entity_makes_no_entity_call(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No named entity -> the check is skipped: no entity_Noul in any
    decide call, and the run answers as before."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY, AW2000_WARRANTY, AW2000_PORT])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=[])
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(
            db, chat, user_a, message_id, "How long does the battery last on a full charge?"
        ),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is None
    for call in jev.sufficient_calls:
        assert not [name for name in call if name.startswith("entity_")]


async def test_entity_noul_rides_the_sufficient_call(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TRD §7.1: the per-passage Noul is batched into the existing
    post-sanitize decide call — never a sequential extra call."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY, AW2000_WARRANTY, AW2000_PORT])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=[])
    await prepare_auto_run(
        get_session_factory(),
        await _params(
            db,
            chat,
            user_a,
            message_id,
            "What ingress protection rating does every Kestrel model carry?",
        ),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert jev.sufficient_calls, "the sufficiency call must have run"
    for call in jev.sufficient_calls:
        assert "sufficient" in call
        entity_names = [name for name in call if name.startswith("entity_")]
        assert len(entity_names) == 3, "one Noul per top-k passage, in the same call"
        # The prompt carries the question and the passage, never a bare
        # string the judge cannot relate to the question.
        for name in entity_names:
            assert "Kestrel" in call[name].prompt
            assert "[passage]" in call[name].prompt


floor = threshold("entity_match", "jev")


@pytest.mark.parametrize("p", [floor, floor - 0.001])
async def test_entity_match_threshold_boundary(
    p: float,
    db: AsyncSession,
    user_a: Any,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the floor a passage matches; just under it the run abstains."""
    chat, message_id = await _seed_chat(db, user_a)
    chunks = await _corpus(db, user_a, [AW2000_BATTERY])
    _patch_pipeline(monkeypatch, chunks, no_llm)

    jev = _EntityJev(matching=["AW-2000"], yes=p, no=0.0)
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id, "How long is the warranty on the AW-2000?"),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    if p >= floor:
        assert run.abstain_event is None
    else:
        assert run.abstain_event is not None
        assert run.contexts == []
