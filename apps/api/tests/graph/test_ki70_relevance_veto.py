"""KI-70: a gist question is not subject to the relevance veto.

Phase 1c item 2. The KI-26 relevance gate measures question-to-passage *lexical
overlap*, and "can you give me the gist of X" matches no single passage — which
is why `broad-alice` scored 0.35 on the right passages while the KI-54 entity
check scored 0.97 on those same passages. The rule: for `summarize` intent the
veto is switched off and sufficiency plus the entity check decide alone.

Every number in this file is one the runs recorded, not one chosen here. The
sources are `docs/reviews/2026-10-12-2031-ki70-signals.md` §3, which replays
the whole table, and the two phase-1b acceptance exports behind it.

Two halves:

- `RECORDED_ITEMS` is that replay as data, and
  `test_the_rule_turns_no_should_decline_item_into_an_answer` is the brief's
  acceptance test — it fails if any recorded abstention flips.
- the rest drive the real `prepare_auto_run` with the recorded values, so the
  rule is pinned in the code path and not only in a table.

Jev is a fixture and the generator is a stub; no live model.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions import threshold
from decisions.engine import DecisionEngine
from graph.auto import AutoRun, AutoRunInput, prepare_auto_run

# `no_llm` is imported as a fixture, not a helper: it is what stubs the
# generator and the embeddings, and a test that ran without it would reach a
# live provider (testing.md).
from tests.graph.test_chitchat import _gate_params, _RelevanceJev
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user

# The thresholds the rule replays against, read from `decisions/thresholds.py`
# rather than restated, so a threshold change cannot leave this file asserting a
# stale bar.

SUFFICIENT_ABSTAIN = threshold("sufficient_abstain", "jev")
RERANK_ABSTAIN = threshold("rerank_abstain", "jev")
ENTITY_MATCH = threshold("entity_match", "jev")

# One row per item that reached a gate decision in either phase-1b run:
# (id, expect, got, intent, sufficient on the last attempt, relevance on the
# last attempt). Source: docs/reviews/2026-10-12-2031-ki70-signals.md, run 1
# unless marked run 2. Items that never reached the gate (smalltalk, library,
# the two KI-71 chitchat items) are absent by construction, not by omission.
#
# `got` is what the run actually did, and it carries the one signal this table
# cannot read directly. The KI-54 entity check (`entity_match`, floor 0.50) was
# recorded as `decision` events in the acceptance stack's database,
# `veriforge_accept_phase1b`, which no longer exists — so entity values are not
# recoverable (the doc's header says so). They are not needed as data: for an
# item where sufficiency and relevance BOTH clear, the recorded `got` decides
# the entity check by itself. `outside-holmes-boston` is the case that makes it
# matter — sufficiency 0.39 and relevance 0.63, both over their floors, and the
# run still declined, so the entity check is what held it. Dropping the entity
# check from a replay would turn that into a confident wrong answer, which is
# precisely the regression the rule must not cause.
RECORDED_ITEMS: list[tuple[str, str, str, str, float, float]] = [
    ("broad-frankenstein", "answer", "answer", "summarize", 0.47, 0.67),
    ("quote-darcy", "answer", "answer", "lookup", 0.76, 0.95),
    ("character-collins", "answer", "answer", "lookup", 0.82, 0.97),
    ("fact-bennet-sisters", "answer", "answer", "lookup", 0.94, 0.97),
    ("fact-irene-adler", "answer", "answer", "lookup", 0.80, 0.93),
    ("plot-red-headed-league", "answer", "answer", "lookup", 0.82, 0.97),
    ("plot-speckled-band", "answer", "answer", "lookup", 0.85, 0.95),
    ("fact-morlocks", "answer", "answer", "lookup", 0.84, 0.97),
    ("fact-weena", "answer", "answer", "lookup", 0.64, 0.95),
    ("scene-tea-party", "answer", "answer", "lookup", 0.87, 0.97),
    ("frame-walton", "answer", "answer", "lookup", 0.89, 0.94),
    ("compare-inventors", "answer", "answer", "compare", 0.13, 0.97),
    ("followup-adler", "answer", "answer", "lookup", 0.66, 0.88),
    ("outside-whitman", "answer", "answer", "lookup", 0.14, 0.78),
    ("outside-whitman-lilacs", "not_in_sources", "not_in_sources", "lookup", 0.02, 0.11),
    ("outside-study-in-scarlet", "not_in_sources", "not_in_sources", "lookup", 0.07, 0.26),
    ("outside-general", "not_in_sources", "not_in_sources", "lookup", 0.02, 0.02),
    ("outside-moriarty", "not_in_sources", "not_in_sources", "lookup", 0.04, 0.29),
    ("outside-emma", "not_in_sources", "not_in_sources", "lookup", 0.08, 0.24),
    ("outside-war-of-the-worlds", "not_in_sources", "not_in_sources", "lookup", 0.02, 0.03),
    ("outside-dracula", "not_in_sources", "not_in_sources", "lookup", 0.02, 0.07),
    ("outside-looking-glass", "not_in_sources", "not_in_sources", "lookup", 0.05, 0.07),
    ("outside-moby-dick", "not_in_sources", "not_in_sources", "lookup", 0.04, 0.71),
    ("ml-fr-bovary-death", "answer", "answer", "lookup", 0.82, 0.94),
    ("ml-de-samsa", "answer", "answer", "lookup", 0.93, 0.97),
    ("ml-tl-maria-clara", "answer", "answer", "lookup", 0.63, 0.92),
    ("ml-zh-wukong-weapon", "answer", "answer", "lookup", 0.95, 0.98),
    ("ml-ja-rashomon-oldwoman", "answer", "answer", "lookup", 0.91, 0.96),
    ("xl-en-bovary-death", "answer", "answer", "lookup", 0.86, 0.90),
    ("xl-en-samsa", "answer", "answer", "lookup", 0.87, 0.96),
    ("xl-en-wukong-master", "answer", "answer", "lookup", 0.92, 0.94),
    ("ml-es-outside", "not_in_sources", "not_in_sources", "lookup", 0.04, 0.05),
    ("ml-fr-outside", "not_in_sources", "not_in_sources", "lookup", 0.15, 0.50),
    ("ml-de-outside", "not_in_sources", "not_in_sources", "lookup", 0.03, 0.24),
    ("ml-zh-outside", "not_in_sources", "not_in_sources", "lookup", 0.04, 0.02),
    ("ml-ja-outside", "not_in_sources", "not_in_sources", "lookup", 0.13, 0.48),
    ("outside-holmes-mycroft", "not_in_sources", "not_in_sources", "lookup", 0.06, 0.07),
    ("outside-holmes-boston", "not_in_sources", "not_in_sources", "lookup", 0.39, 0.63),
    ("ml-de-bovary-animal", "not_in_sources", "not_in_sources", "lookup", 0.06, 0.26),
    ("ml-fr-noli-baiser", "not_in_sources", "not_in_sources", "lookup", 0.08, 0.15),
    ("ml-zh-xiyou-nezha", "not_in_sources", "not_in_sources", "lookup", 0.24, 0.16),
    ("ml-ja-rashomon-rokuro", "not_in_sources", "not_in_sources", "lookup", 0.29, 0.29),
    ("broad-alice", "answer", "answer", "summarize", 0.61, 0.35),
    ("broad-time-machine", "answer", "answer", "summarize", 0.67, 0.95),
    ("broad-quijote", "answer", "answer", "summarize", 0.85, 0.91),
    ("broad-verwandlung", "answer", "answer", "summarize", 0.67, 0.89),
    ("broad-wukong", "answer", "answer", "summarize", 0.88, 0.91),
    ("broad-bovary", "answer", "answer", "summarize", 0.50, 0.57),
    ("amb-frankenstein-addressee", "answer", "answer", "lookup", 0.84, 0.96),
    ("amb-alice-sister", "answer", "answer", "lookup", 0.31, 0.87),
    # Relabelled `answer` -> `not_in_sources` on 2026-10-12: the eye scene the
    # item asked about is not in this edition of the corpus. It is `lookup`
    # intent either way, so the exemption never reached it, and it still
    # declines — which is the correct outcome for the label it now carries.
    ("amb-bovary-homais", "not_in_sources", "not_in_sources", "lookup", 0.15, 0.39),
    # run 2 (7c7a0c1), the 5-id rerun
    ("ml-es-rocinante", "answer", "answer", "lookup", 0.97, 0.99),
    ("broad-alice", "answer", "answer", "summarize", 0.56, 0.43),
    ("broad-bovary", "answer", "answer", "summarize", 0.42, 0.65),
    ("amb-bovary-homais", "not_in_sources", "not_in_sources", "lookup", 0.16, 0.39),
]


def entity_ok(got: str, expect: str, sufficient: float, relevance: float) -> bool:
    """Whether the KI-54 entity check passed, as the run's own verdict records it.

    Only decidable where the other two signals leave the verdict open: when
    sufficiency and relevance BOTH clear their floors, the entity check is the
    only thing left, so the run's own outcome IS its reading — answered means it
    passed, declined means it abstained (`graph/auto.py:1306`, `:1376`).
    Everywhere else the entity check did not decide the verdict, and it is
    reported as passing: a placeholder, not a claim, and every item where the
    placeholder would matter is asserted by name below.

    `outside-holmes-boston` is that item: sufficiency 0.39 and relevance 0.63
    both clear, and the run declined anyway. KI-54's entity check held it — the
    retrieved passages were about Sherlock Holmes, but not about Mary Bostan.
    Replaying without this column would report a confident wrong answer the run
    never gave, which is exactly the regression the rule must not cause.
    """
    if sufficient >= SUFFICIENT_ABSTAIN and relevance >= RERANK_ABSTAIN:
        return got == "answer"
    return True


def answers_now(sufficient: float, relevance: float) -> bool:
    """The gate's own decision with the veto in force."""
    return sufficient >= SUFFICIENT_ABSTAIN and relevance >= RERANK_ABSTAIN


def answers_under_rule(intent: str, sufficient: float, relevance: float) -> bool:
    """The same decision with the KI-70 exemption applied to `summarize`.

    The veto PASSES when the relevance score clears its floor, or when the
    question is a gist question — which is the whole rule: for `summarize`,
    lexical overlap is not the signal, so there is nothing to veto on.
    """
    veto_passes = relevance >= RERANK_ABSTAIN or intent == "summarize"
    return sufficient >= SUFFICIENT_ABSTAIN and veto_passes


def _decides_to_answer(
    intent: str, sufficient: float, relevance: float, entity_passed: bool = True
) -> bool:
    """The full gate decision (`graph/auto.py:1306`): sufficiency AND relevance
    AND the entity check."""
    return answers_under_rule(intent, sufficient, relevance) and entity_passed


def test_the_thresholds_this_file_replays_against_are_the_shipped_ones() -> None:
    """The numbers below are only meaningful against these floors. If a
    threshold moves, this file must stop claiming to replay the runs."""
    assert (SUFFICIENT_ABSTAIN, RERANK_ABSTAIN, ENTITY_MATCH) == (0.05, 0.60, 0.50)


def test_the_rule_turns_no_should_decline_item_into_an_answer() -> None:
    """The brief's acceptance test, on every recorded item of both runs, with
    the entity check read off the run's own verdict where it decided."""
    regressions = [
        (id_, intent, sufficient, relevance)
        for id_, expect, got, intent, sufficient, relevance in RECORDED_ITEMS
        if expect == "not_in_sources"
        and _decides_to_answer(
            intent, sufficient, relevance, entity_ok(got, expect, sufficient, relevance)
        )
        and not answers_now(sufficient, relevance)
    ]
    assert regressions == []


def test_the_rule_removes_exactly_the_broad_false_abstentions() -> None:
    """And it has to remove some, or it is a rule that does nothing."""
    gained = [
        (id_, sufficient, relevance)
        for id_, expect, got, intent, sufficient, relevance in RECORDED_ITEMS
        if expect == "answer"
        and _decides_to_answer(
            intent, sufficient, relevance, entity_ok(got, expect, sufficient, relevance)
        )
        and not answers_now(sufficient, relevance)
    ]
    assert sorted({id_ for id_, _, _ in gained}) == ["broad-alice", "broad-bovary"]
    # Every one of them clears the sufficiency floor comfortably, which is what
    # makes the exemption safe here: the veto was the only thing holding them.
    assert all(sufficient >= 0.42 for _, sufficient, _ in gained)
    assert all(relevance < RERANK_ABSTAIN for _, _, relevance in gained)


def test_the_entity_check_is_what_holds_the_one_abstention_that_clears_both_floors() -> None:
    """`outside-holmes-boston`: sufficiency 0.39, relevance 0.63, both over
    their floors, and the run declined. If the replay dropped the entity check
    this item would read as a confident wrong answer — so the column exists,
    and this asserts it is still load-bearing."""
    row = next(
        r for r in RECORDED_ITEMS if r[0] == "outside-holmes-boston" and r[3] == "lookup"
    )
    _id, expect, got, _intent, sufficient, relevance = row
    assert sufficient >= SUFFICIENT_ABSTAIN and relevance >= RERANK_ABSTAIN
    assert entity_ok(got, expect, sufficient, relevance) is False
    assert not _decides_to_answer("lookup", sufficient, relevance, entity_passed=False)


def test_the_exemption_never_reaches_a_should_decline_item() -> None:
    """The mechanism, stated as its own test: no recorded abstention was
    classified `summarize`, so no recorded abstention can be exempted."""
    assert {
        intent for _, expect, _got, intent, _, _ in RECORDED_ITEMS if expect == "not_in_sources"
    } == {"lookup"}


def test_the_exemption_does_not_rescue_an_item_sufficiency_holds_down() -> None:
    """`amb-bovary-homais`, both runs: intent `lookup`, so the veto was never
    the thing abstaining it — sufficiency at 0.15/0.16 was. The exemption must
    not turn that into an answer either."""
    for sufficient, relevance in ((0.15, 0.39), (0.16, 0.39)):
        assert not answers_under_rule("lookup", sufficient, relevance)


def test_a_summarize_question_below_the_sufficiency_floor_still_declines() -> None:
    """The exemption removes ONE signal. A gist question whose passages do not
    answer it still declines — otherwise the rule would answer summaries out of
    topically-adjacent evidence, which is the failure KI-26 exists to prevent."""
    assert not answers_under_rule("summarize", 0.02, 0.35)
    assert not answers_under_rule("summarize", 0.04, 0.02)


def test_a_summarize_question_the_entity_check_fails_still_declines() -> None:
    """The second signal the exemption does NOT touch. Suffixed because the
    recorded data has no `summarize` abstention to measure this on: the risk is
    structural, and this pins the structure rather than a measurement."""
    assert not _decides_to_answer("summarize", 0.61, 0.35, entity_passed=False)


def test_the_rule_does_not_lower_the_relevance_floor_for_anything_else() -> None:
    """`outside-moby-dick` clears relevance at 0.71 and is held by sufficiency
    at 0.04; `outside-holmes-boston` clears at 0.63 and is held by the entity
    check at 0.39. Both are `lookup`, so the recorded data does not show what a
    `summarize` should-decline item would do — but nothing here widens the
    floor for the intents that are recorded."""
    for id_, expect, got, intent, sufficient, relevance in RECORDED_ITEMS:
        if expect == "not_in_sources" and relevance >= RERANK_ABSTAIN:
            assert not _decides_to_answer(
                intent, sufficient, relevance, entity_ok(got, expect, sufficient, relevance)
            ), id_


def test_the_table_matches_the_published_signals_doc() -> None:
    """The doc is the artefact the brief asks for; this keeps it from drifting
    away from the code that implements what it claims."""
    doc = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "reviews"
        / "2026-10-12-2031-ki70-signals.md"
    ).read_text(encoding="utf-8")
    for id_, _expect, _got, _intent, _sufficient, _relevance in RECORDED_ITEMS:
        assert f"`{id_}`" in doc, id_
    assert "summarize" in doc and "relevance veto" in doc


def test_the_two_broad_items_carry_the_recorded_values_in_the_doc() -> None:
    doc = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "reviews"
        / "2026-10-12-2031-ki70-signals.md"
    ).read_text(encoding="utf-8")
    # `broad-alice`: sufficient 0.61 against relevance 0.35, and the entity
    # check at 0.97 on the same passages. That pair IS the case.
    assert "0.61" in doc and "0.35" in doc and "0.97" in doc
    assert "broad-bovary" in doc


# --- the rule in the code path, with the recorded values -------------------


@pytest.fixture
async def summarise_params(
    db: AsyncSession,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> AutoRunInput:
    """`_gate_params` seeds four answerable passages and pins the real
    JevRerank, so the relevance gate runs on the fake's values. `no_llm` is
    required, not optional: it stubs `complete` and the embeddings, and
    without it this file would reach a live provider (testing.md)."""
    user = await make_user(db, "ki70-summarise@test.dev")
    return await _gate_params(db, user, no_llm, monkeypatch)


async def _summarise_run(
    params: AutoRunInput, *, intent: str, sufficient: float, relevance: float
) -> AutoRun:
    return await prepare_auto_run(
        get_session_factory(),
        params,
        DecisionEngine(jev=_RelevanceJev(intent, sufficient, relevance), mode="jev_only"),
    )


def _relevance(run: AutoRun) -> list[Any]:
    return [d for d in run.decision_events if d.name == "relevance"]


@pytest.mark.asyncio
async def test_a_gist_question_answers_on_sufficiency_alone(
    summarise_params: AutoRunInput,
) -> None:
    """`broad-alice`'s recorded run: sufficiency 0.61 clears the 0.05 floor by
    a mile, relevance 0.35 is far under the 0.60 veto, and the entity check
    says these passages are about the named document (0.97). With the veto
    waived the run answers."""
    run = await _summarise_run(
        summarise_params, intent="summarize", sufficient=0.61, relevance=0.35
    )

    assert run.ingress.intent == "summarize"
    assert run.abstain_event is None
    assert run.contexts, "a gated-in gist question generates from its contexts"
    assert run.sufficiency_p == pytest.approx(0.61)
    # The relevance decision is still published, at its real value — the
    # exemption changes the VERDICT, not the measurement, so the trace still
    # shows the score and says the veto was waived.
    decisions = _relevance(run)
    assert decisions[-1].value == pytest.approx(0.35)
    assert decisions[-1].threshold == pytest.approx(0.60)
    assert "waived" in decisions[-1].reasoning


@pytest.mark.asyncio
async def test_the_same_question_still_declines_when_its_evidence_does_not_answer_it(
    summarise_params: AutoRunInput,
) -> None:
    """The other half, and the one that matters: waiving the veto must not turn
    a gist question into an answer from topically-adjacent passages."""
    run = await _summarise_run(
        summarise_params, intent="summarize", sufficient=0.02, relevance=0.35
    )

    assert run.ingress.intent == "summarize"
    assert run.abstain_event is not None
    assert run.contexts == []


@pytest.mark.asyncio
async def test_a_lookup_question_is_unaffected_by_the_exemption(
    summarise_params: AutoRunInput,
) -> None:
    """The exemption is keyed on intent, not on the score. The same values
    under `lookup` abstain exactly as they did before."""
    run = await _summarise_run(
        summarise_params, intent="lookup", sufficient=0.61, relevance=0.35
    )

    assert run.ingress.intent == "lookup"
    assert run.abstain_event is not None
    assert "waived" not in _relevance(run)[-1].reasoning


@pytest.mark.asyncio
async def test_a_gist_question_that_clears_relevance_is_unchanged(
    summarise_params: AutoRunInput,
) -> None:
    """`broad-quijote` (0.85 / 0.91): both signals already agreed. The rule is
    a no-op there, which is what keeps it from being a behaviour change for the
    broad items that were already passing."""
    run = await _summarise_run(
        summarise_params, intent="summarize", sufficient=0.85, relevance=0.91
    )

    assert run.abstain_event is None
    assert run.contexts


@pytest.mark.asyncio
async def test_the_exemption_is_a_veto_waiver_and_not_a_threshold_change(
    summarise_params: AutoRunInput,
) -> None:
    """`rerank_abstain` is still 0.60 and the published decision still carries
    it. A rule that quietly lowered the floor would move every other item too;
    this one cannot, because the score never reaches the comparison."""
    run = await _summarise_run(
        summarise_params, intent="summarize", sufficient=0.61, relevance=0.35
    )

    assert _relevance(run)[-1].threshold == pytest.approx(RERANK_ABSTAIN)
    assert _relevance(run)[-1].threshold == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_a_non_jev_reranker_is_unaffected_on_a_gist_question(
    db: AsyncSession,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption only speaks where a relevance score exists. With a
    non-Jev provider the gate is skipped (NVIDIA/Cohere are on other scales),
    so the rule has nothing to waive and nothing changes."""

    class _LowScoringProvider:
        def __init__(self, *_args: object) -> None:
            pass

        async def rerank(
            self, *, query: str, documents: list[str], top_n: int
        ) -> list[tuple[int, float]]:
            return [(i, 0.3) for i in range(min(top_n, len(documents)))]

    user = await make_user(db, "ki70-nonjev@test.dev")
    params = await _gate_params(
        db,
        user,
        no_llm,
        monkeypatch,
        reranker_factory=_LowScoringProvider,
    )
    run = await _summarise_run(
        params, intent="summarize", sufficient=0.61, relevance=0.3
    )

    assert run.abstain_event is None
    assert _relevance(run) == []


def test_the_relabelled_item_is_not_in_the_answer_class() -> None:
    """`amb-bovary-homais` is a should-decline from 2026-10-12 (phase 1c item
    2). Pinned here as well as in the set's own test, because the KI-70 table
    above lists it and the two must not tell different stories."""
    path = Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json"
    items = {item["id"]: item for item in json.loads(path.read_text())["items"]}

    assert items["amb-bovary-homais"]["expect"] == "not_in_sources"
    assert items["amb-bovary-homais"].get("relabelled")
    assert items["amb-bovary-homais"].get("spot_read")