"""Beta lane B, item 6: skip the query variants on simple single-hop lookups.

TRD §7.1 lists it among P3's structural changes, and the brief calls it the
riskiest item in the lane — the variants are also what makes multi-query recall
work when the embedding misses the phrasing. So the setting DEFAULTS TO OFF,
and item 7 is what would turn it on.

These tests therefore cover both settings, and they check the two things that
would make it dangerous rather than merely different:

* the condition is `complexity = single` AND `intent = lookup` — not either
  alone. A multi-part question's parts and a compare question's entities are
  separate retrievals, not phrasings; skipping those is the KI-12 abstention
  (`outside-whitman`, the Darcy turn that abstained because its second part
  was never retrieved).
* with the setting on, the run retrieves ONCE and on the rewritten question
  itself — no variants LLM call, one embedding, one search.

Real Postgres; Jev, the reranker and the small LLM are fakes.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import (
    SKIP_VARIANTS_SIMPLE_LOOKUP,
    AutoRunInput,
    _skip_variants_for,
    prepare_auto_run,
)
from graph.ingress import IngressOutcome
from retrieval.filters import ClientFilters
from retrieval.rerank import JevRerank
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.decisions import Answer, Question
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user, vec

PASSAGE = "The AW-2000 warranty is 24 months from the date of purchase."


def _ingress(**overrides: Any) -> IngressOutcome:
    values: dict[str, Any] = {
        "intent": "lookup",
        "source": "upload",
        "complexity": "single",
        "risk": "low",
        "lexical_weight": 0.5,
        "guard_injection": "pass",
        "guard_jailbreak": "pass",
        "guard_pii": "pass",
        "off_topic": "pass",
    }
    values.update(overrides)
    return IngressOutcome(**values)


def _setting(value: bool) -> Any:
    settings = RuntimeSettings.from_data(
        100, {"retrieval": {"skip_variants_simple_lookup": value}}
    )
    return set_runtime_settings(settings)


# --- the condition -----------------------------------------------------------


def test_the_setting_defaults_to_off() -> None:
    """The lane's own instruction: do not turn it on unless item 7 shows no
    recall or quality loss on every set. This test is the tripwire for that."""
    assert SKIP_VARIANTS_SIMPLE_LOOKUP is False


def test_off_by_default_means_a_plain_lookup_keeps_its_variants() -> None:
    assert _skip_variants_for(_ingress()) is False


def test_on_skips_only_a_single_hop_lookup() -> None:
    token = _setting(True)
    try:
        assert _skip_variants_for(_ingress()) is True
    finally:
        reset_runtime_settings(token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"complexity": "multi"},
        {"intent": "multi-part"},
        {"intent": "compare"},
        {"intent": "summarize"},
    ],
)
def test_on_but_not_a_simple_lookup_still_generates_variants(overrides: dict[str, Any]) -> None:
    """Either condition alone is not enough. A multi-part question's parts and
    a compare question's entities are DIFFERENT QUESTIONS, not phrasings:
    dropping them is the KI-12 abstention, not a latency win."""
    token = _setting(True)
    try:
        assert _skip_variants_for(_ingress(**overrides)) is False
    finally:
        reset_runtime_settings(token)


# --- through the pipeline -----------------------------------------------------


class _AnsweringJev(_IngressJev):
    """Sufficiency high enough to answer, and a fixed verdict per rerank
    passage. Records how many phrasings the small model was asked for."""

    def __init__(self, intent: str = "lookup") -> None:
        super().__init__(intent)
        self.rewriter_calls = 0

    async def decide(
        self, *, state: Any, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        self.rewriter_calls += 0  # the small LLM is counted in the test, not here
        answers = await super().decide(state=state, questions=questions)
        for name in questions:
            if name == "sufficient":
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.9, probability=0.9)
            elif name.startswith("passage_"):
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.9, probability=None)
        return answers


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-variants@test.dev")


async def _run(
    db: AsyncSession, user: Any, monkeypatch: pytest.MonkeyPatch, *, intent: str = "lookup"
) -> tuple[Any, dict[str, list[Any]]]:
    chat, message_id = await _seed_chat(db, user)
    calls: dict[str, list[Any]] = {"complete": [], "embed": [], "search": []}

    async def fake_complete(**_kwargs: Any) -> str:
        calls["complete"].append(1)
        return "How long is the AW-2000 warranty?\nAnd how do I claim it?"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        calls["embed"].append(list(texts))
        return [vec(1) for _ in texts]

    async def fake_search(*_args: Any, **kwargs: Any) -> list[Any]:
        calls["search"].append(str(kwargs["query_text"]))
        return []

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    monkeypatch.setattr(
        auto_module, "get_reranker", lambda engine=None, run_id="": JevRerank(engine, run_id)
    )

    from sqlalchemy import select

    from db.models import Collection

    collection_id = (
        await db.execute(
            select(Collection.id).where(Collection.owner_id == user.id).limit(1)
        )
    ).scalar_one()
    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )
    run = await prepare_auto_run(
        get_session_factory(), params, DecisionEngine(jev=_AnsweringJev(intent), mode="jev_only")
    )
    return run, calls


async def test_off_the_run_still_makes_the_variants_call(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, calls = await _run(db, user_a, monkeypatch)

    assert len(calls["complete"]) >= 2, "rewrite + variants, as before"
    assert len(calls["search"]) >= 2, "the rewritten question plus its variants"


async def test_on_a_simple_lookup_retrieves_once_on_the_rewritten_question(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _setting(True)
    try:
        run, calls = await _run(db, user_a, monkeypatch)
    finally:
        reset_runtime_settings(token)

    assert len(calls["complete"]) == 1, "only the rewrite — no variants LLM call"
    assert len(calls["embed"]) == 1
    # One query, one vector. The embedding text is the normalised form (lower
    # case, collapsed whitespace) — the same text the cache keys on.
    assert len(calls["embed"][0]) == 1
    assert calls["embed"][0][0].startswith("how long is the aw-2000 warranty?")
    # One search, on the rewritten question itself — the query `complete`
    # returned, which is what every variant path seeds its first query with.
    assert len(calls["search"]) == 1, f"one search: {calls['search']}"
    assert calls["search"][0] == "How long is the AW-2000 warranty?\nAnd how do I claim it?"
    assert run.abstain_event is None, "it still answers; the gate is unchanged"


async def test_on_a_multi_part_question_still_asks_for_its_parts(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this guards is the one the item risks: a multi-part
    question retrieves on each part, and losing them means abstaining on a
    question the corpus can answer (KI-12)."""
    token = _setting(True)
    try:
        _, calls = await _run(db, user_a, monkeypatch, intent="multi-part")
    finally:
        reset_runtime_settings(token)

    assert len(calls["complete"]) >= 3, "rewrite + variants + parts"
    assert len(calls["search"]) >= 3