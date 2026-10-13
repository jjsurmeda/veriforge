""": lane B item 6 is removed, and cannot be turned on by accident.

TRD §7.1 lists "skip query variants on simple single-hop lookups" among P3's
structural changes, and lane B shipped it behind
`retrieval.skip_variants_simple_lookup`, off by default. Item 7's measurement
is what closed it: with the setting ON, fast20 answered **1 of 12** answerable
items — `answer_rate` 0.917 -> 0.083 — while **faithfulness went UP to 1.0**.
The declines were clean, so no confidence metric caught it and no part of the
eval gate gates `answer_rate` against a floor for that subset. Only a reader
comparing latency alone would have turned it on.

The setting's premise was that a single-hop lookup question "already retrieves
well" on its own. On this corpus it does not. Quoting the item whole, the
answer was in the corpus the whole time (`Torque the retaining screw to
4 Nm.` is in `eval-seed-corpus`, verified by direct query), but the question's
own wording does not match it lexically enough to retrieve, and the three LLM
rephrasings were what bridged the gap. Removing them removed the recall.

**Removed, not disabled.** Nothing else reads it, and a setting that is off by
default is one admin click away from a 92% answer-rate collapse — while the
evidence against it lives in a document rather than in the code, where the
next person to look will not be. So there is no knob here at all, and the
comment at the call site says why.

These tests therefore assert two things:

* the code that read the setting is gone, and no module in the package
  references the key — so setting it in the admin API is a no-op rather than
  a slow-motion way to break the product;
* the retrieval path is unchanged: the variants LLM call still happens, on
  every intent, including the multi-part and compare cases whose per-part and
  per-entity queries were never phrasings to begin with.

Real Postgres; Jev, the reranker and the small LLM are fakes.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import AutoRunInput, prepare_auto_run
from graph.ingress import IngressOutcome
from retrieval.filters import ClientFilters
from retrieval.rerank import JevRerank
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.decisions import Answer, Question
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user, vec

SETTING_KEY = "skip_variants_simple_lookup"


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
    settings = RuntimeSettings.from_data(100, {"retrieval": {SETTING_KEY: value}})
    return set_runtime_settings(settings)


# --- the code is gone ---------------------------------------------------------


def test_the_skip_helper_no_longer_exists() -> None:
    """Not "it returns False": the function itself has to be gone, because a
    helper that always says no is one edit away from saying yes."""
    assert not hasattr(auto_module, "_skip_variants_for")
    assert not hasattr(auto_module, "SKIP_VARIANTS_SIMPLE_LOOKUP")


def test_no_module_in_the_package_reads_the_setting() -> None:
    """The tripwire for "cannot be turned on by accident".

    An admin `PATCH /admin/settings` with
    `{"retrieval": {"skip_variants_simple_lookup": true}}` still validates —
    `retrieval` is an open dict in `_ALLOWED_SETTINGS` and the key is
    arbitrary. What must not exist is a reader.

    Checked over the parsed AST rather than the raw text, because the key is
    named on purpose in `auto.py`'s comment at the call site (that comment is
    the record of why there is no knob here, and it is what a later reader
    finds first). A text search would fail on the explanation and pass on the
    branch; this one fails only on code. If it trips, someone re-added the
    branch and the measurement behind this file is the reason not to.
    """
    import ast
    import pathlib

    offenders: list[str] = []
    roots = [
        pathlib.Path(auto_module.__file__).parent,
        pathlib.Path(auto_module.__file__).parent / "stages",
    ]
    for root in roots:
        for path in sorted(root.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == SETTING_KEY:
                    offenders.append(f"{path.name}:{node.lineno}")
                    break
    assert offenders == [], (
        f"{offenders} still read {SETTING_KEY!r};  measured it collapsing "
        "fast20 from 11/12 answered to 1/12"
    )


def test_the_runtime_setting_can_be_set_and_does_nothing() -> None:
    """The behaviour that matters, stated as behaviour: an owner who sets the
    key anyway gets a valid settings row and an unchanged pipeline. This is
    what "cannot be turned on by accident" means in practice."""
    token = _setting(True)
    try:
        settings = RuntimeSettings.from_data(100, {"retrieval": {SETTING_KEY: True}})
        assert settings.data["retrieval"][SETTING_KEY] is True, (
            "the key is still accepted by the settings layer — it is simply "
            "unread, which is what makes setting it a no-op rather than an error"
        )
    finally:
        reset_runtime_settings(token)


# --- the retrieval path is unchanged -----------------------------------------


class _AnsweringJev(_IngressJev):
    """Sufficiency high enough to answer, and a fixed verdict per rerank
    passage. Records how many phrasings the small model was asked for."""

    def __init__(self, intent: str = "lookup") -> None:
        super().__init__(intent)
        self.rewriter_calls = 0

    async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
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
        await db.execute(select(Collection.id).where(Collection.owner_id == user.id).limit(1))
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


async def test_a_plain_lookup_still_makes_the_variants_call(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path with item 6 absent must be byte-for-byte the path that shipped
    before it: rewrite plus variants, the rewritten question plus its variants
    searched."""
    _, calls = await _run(db, user_a, monkeypatch)

    assert len(calls["complete"]) >= 2, "rewrite + variants, as before"
    assert len(calls["search"]) >= 2, "the rewritten question plus its variants"


async def test_the_setting_cannot_change_what_the_pipeline_does(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set the key to `true` and the run must be identical to the run with it
    unset. Asserted as an equality of the calls, not as a count: a count
    happens to be equal for the wrong reason often enough to matter here.

    Compared on the *variants LLM call and the searches* only. The embedding
    batch legitimately differs between two back-to-back runs because the
    first one populates `query_cache` and the second reads it — that is the
    cache working, not the setting, and including it would have made this
    test fail for the wrong reason. The variants call is the one item 6
    removed, so it is the one that has to match.
    """
    _, without = await _run(db, user_a, monkeypatch)

    token = _setting(True)
    try:
        _, with_setting = await _run(db, user_a, monkeypatch)
    finally:
        reset_runtime_settings(token)

    assert with_setting["complete"] == without["complete"]
    assert with_setting["search"] == without["search"], (
        f"the setting changed what was retrieved: {with_setting['search']} vs {without['search']}"
    )

    assert with_setting["complete"] == without["complete"], (
        f"the setting changed the variants LLM calls: "
        f"{with_setting['complete']} vs {without['complete']}"
    )
    assert with_setting["search"] == without["search"], (
        f"the setting changed what was retrieved: {with_setting['search']} vs {without['search']}"
    )


async def test_a_multi_part_question_still_asks_for_its_parts(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression item 6 risked, now unrecoverable: a multi-part question
    retrieves on each part, and losing them means abstaining on a question the
    corpus can answer. Per-part queries were never phrasings, so they
    were never candidates for skipping."""
    _, calls = await _run(db, user_a, monkeypatch, intent="multi-part")

    assert len(calls["complete"]) >= 3, "rewrite + variants + parts"
    assert len(calls["search"]) >= 3
