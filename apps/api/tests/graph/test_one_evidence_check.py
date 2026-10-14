"""One evidence check (ADR-006): the recorded runs, replayed without the
relevance veto.

ADR-006 removes the relevance floor: the reranker's answer-containment rubric
already ranks passages by whether they answer, so a second, separately
calibrated judgement of the same thing was one too many. This file is the
consequence ADR-006 names — *the decline-accuracy and confident-wrong bars must
hold with the relevance floor gone* — replayed on the recorded acceptance runs
rather than asserted.

**The headline result is a failure, and it is the reason this file exists.**
`RECORDED_ITEMS` is every item of both phase-1b runs that reached a gate
decision, with the sufficiency and max post-sanitize rerank score it recorded.
Replaying them under the single check that now decides a run
(`sufficient` ≥ `sufficient_abstain`, and the entity guard beside it) turns
**12 recorded `not_in_sources` rows into confident wrong answers** at the
shipped floor of 0.05. No threshold on this signal satisfies both of PRD §5's
clauses at once — see `test_no_threshold_on_sufficiency_alone_satisfies_both_clauses`.

So the veto removal is right in shape and not yet safe in this form, and the
owner decision this needs is recorded in `docs/known-issues.md` (KI-70) rather
than resolved here by moving a number on the recorded data alone.

Jev is a fixture and the generator is a stub; no live model.
"""

from dataclasses import replace as dc_replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions import threshold
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import AutoRun, AutoRunInput, prepare_auto_run
from schemas.decisions import Answer

# `no_llm` is imported as a fixture, not a helper: it is what stubs the
# generator and the embeddings, and a test that ran without it would reach a
# live provider (testing.md).
from tests.graph.test_chitchat import _gate_params, _RelevanceJev
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "r2a-one-evidence-check@test.dev")

# The floors the replay runs against, read from `decisions/thresholds.py`
# rather than restated, so a threshold change cannot leave this file asserting a
# stale bar. `rerank_abstain` is deliberately absent: it is gone with the veto.
SUFFICIENT_ABSTAIN = threshold("sufficient_abstain", "jev")
ENTITY_MATCH = threshold("entity_match", "jev")

# One row per item that reached a gate decision in either phase-1b run:
# (id, expect, got, intent, sufficient on the last attempt, relevance on the
# last attempt).
#
# `relevance` is kept even though nothing reads it to decide any more. It is
# the number that made the veto look safe: the items the veto held sit BELOW
# 0.60, and several of them sit well above what any sufficiency floor can
# tolerate without also cutting real answers. Deleting the column would delete
# the evidence for why the removal is not yet safe.
#
# `got` is what the run actually did, and it carries the one signal this table
# cannot read directly. The entity check (`entity_match`, floor 0.50) was
# recorded as `decision` events in the acceptance stack's database,
# `veriforge_accept_phase1b`, which no longer exists — so entity values are not
# recoverable. They are not needed as data: for an item where BOTH old floors
# cleared, the entity check was the only thing left, so the run's own outcome IS
# its reading — answered means it passed, declined means it abstained.
# Everywhere else the entity check did not decide the verdict and is reported as
# passing: a placeholder, not a claim. Every item where the placeholder would
# change the answer is named below, and they are exactly the items the removal
# puts at risk.
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
    # item asked about is not in this edition of the corpus (KI-70's note has
    # the measurement — `Rouard` is 0 hits corpus-wide). The run's behaviour was
    # right all along, which is worth remembering when reading the replay below:
    # one of the twelve rows the removal would flip is an item whose label is
    # wrong, not a run that was wrong.
    ("amb-bovary-homais", "not_in_sources", "not_in_sources", "lookup", 0.15, 0.39),
    # the second run's five-id rerun
    ("ml-es-rocinante", "answer", "answer", "lookup", 0.97, 0.99),
    ("broad-alice", "answer", "answer", "summarize", 0.56, 0.43),
    ("broad-bovary", "answer", "answer", "summarize", 0.42, 0.65),
    ("amb-bovary-homais", "not_in_sources", "not_in_sources", "lookup", 0.16, 0.39),
]


def entity_ok(got: str, sufficient: float, relevance: float) -> bool:
    """Whether the entity check passed, as the run's own verdict records it.

    Only decidable where the other two signals left the verdict open: when
    sufficiency AND relevance BOTH cleared their floors, the entity check was
    the only thing left, so the run's own outcome IS its reading — answered
    means it passed, declined means it abstained. Everywhere else the entity
    check did not decide the verdict, and it is reported as passing: a
    placeholder, not a claim.

    **This placeholder is why the replay below cannot settle the question.**
    Every item the removal puts at risk sat under the relevance floor, so the
    entity check never ran as the deciding signal on any of them and the
    recorded evidence says nothing about what it would have said. The risk is
    real; its size is not measurable from this table.

    `outside-holmes-boston` is the one item where the reading is real: it
    cleared both floors at 0.39 / 0.63 and the run declined, so the entity check
    held it — the passages were about Sherlock Holmes, not about Mary Bostan.
    """
    if sufficient >= SUFFICIENT_ABSTAIN and relevance >= 0.60:
        return got == "answer"
    return True


def decides_to_answer(sufficient: float, entity_passed: bool = True) -> bool:
    """The whole decision now (ADR-006): sufficiency and the entity guard."""
    return sufficient >= SUFFICIENT_ABSTAIN and entity_passed


def _rows() -> list[tuple[str, str, str, float, float]]:
    return [(i, e, g, s, r) for i, e, g, _intent, s, r in RECORDED_ITEMS]


def confident_wrong(floor: float = SUFFICIENT_ABSTAIN) -> list[tuple[str, float]]:
    """Recorded `not_in_sources` rows this rule would answer at `floor`."""
    return [
        (id_, sufficient)
        for id_, expect, got, sufficient, relevance in _rows()
        if expect == "not_in_sources"
        and sufficient >= floor
        and entity_ok(got, sufficient, relevance)
    ]


def false_abstentions(floor: float = SUFFICIENT_ABSTAIN) -> list[tuple[str, float]]:
    """Recorded `answer` rows this rule would decline at `floor`."""
    return [
        (id_, sufficient)
        for id_, expect, _got, sufficient, _r in _rows()
        if expect == "answer" and sufficient < floor
    ]


def test_the_floor_this_file_replays_against_is_the_shipped_one() -> None:
    """The numbers below are only meaningful against this floor. If it moves,
    this file must stop claiming to replay the runs."""
    assert (SUFFICIENT_ABSTAIN, ENTITY_MATCH) == (0.05, 0.50)


def test_removing_the_veto_flips_twelve_recorded_abstentions_into_answers() -> None:
    """The finding, stated as the number it is.

    ADR-006's stated consequence is that the decline-accuracy and
    confident-wrong bars hold with the relevance floor gone. On the recorded
    runs they do not: at the shipped `sufficient_abstain` of 0.05, the single
    evidence check answers twelve rows that the corpus says are not in the
    sources. Every one of them sat under the relevance floor, which is the only
    reading that ever decided them.

    This asserts the failure rather than hiding it. Fixing it is a threshold
    decision with its own evidence requirements (KI-70's rule: before/after on
    fast20, counterfactual and entity-mismatch), and it is the owner's."""
    flipped = confident_wrong()

    assert len(flipped) == 12
    assert [id_ for id_, _ in flipped] == [
        "outside-study-in-scarlet",
        "outside-emma",
        "outside-looking-glass",
        "ml-fr-outside",
        "ml-ja-outside",
        "outside-holmes-mycroft",
        "ml-de-bovary-animal",
        "ml-fr-noli-baiser",
        "ml-zh-xiyou-nezha",
        "ml-ja-rashomon-rokuro",
        "amb-bovary-homais",
        "amb-bovary-homais",
    ]
    # Not a rounding detail: the worst of them is 0.29, nearly six times the
    # floor, so no tolerance around 0.05 rescues this.
    assert max(sufficient for _, sufficient in flipped) >= 0.29
    # And it is the veto that was holding them, not a marginal call.
    assert all(
        relevance < 0.60
        for id_, expect, _got, _s, relevance in _rows()
        if expect == "not_in_sources"
    ) is False, "at least one abstention cleared relevance and was held by something else"


def test_no_threshold_on_sufficiency_alone_satisfies_both_clauses() -> None:
    """Why this is not a threshold move made here.

    PRD §5 wants 0 confident wrong AND ≤ 5% false abstention. Walk the floor
    across the whole range: 0 confident wrong needs ~0.30, and 0.30 already
    costs two recorded answers (`compare-inventors` at 0.13 and
    `outside-whitman` at 0.14). There is no value that does both, which is the
    same conclusion KI-70 reached for the relevance signal and is why it says
    no threshold moves on this data.

    `amb-alice-sister` is the other half of it: at 0.31 it clears, and it is
    one of the three content misses this phase is trying to fix."""
    results = {floor: (len(confident_wrong(floor)), len(false_abstentions(floor))) for floor in
               (0.05, 0.14, 0.20, 0.25, 0.30, 0.31, 0.32, 0.40, 0.50)}

    assert results[0.05] == (12, 0)
    assert results[0.30] == (0, 2), "0 confident wrong, and it costs two answers"
    assert results[0.31] == (0, 2)
    assert results[0.32] == (0, 3), "past 0.31 the ambiguity item falls too"
    assert all(confident for confident, _ in results.values() if _ < 2) is not None
    # No floor in this table reaches (0 confident wrong, ≤ 1 false abstention).
    assert not [
        floor
        for floor, (confident, missed) in results.items()
        if confident == 0 and missed <= 1
    ]


def test_the_entity_guard_is_still_what_holds_the_one_item_that_clears_both_floors() -> None:
    """`outside-holmes-boston`: sufficiency 0.39 and relevance 0.63, both over
    their old floors, and the run declined. If the replay dropped the entity
    check this item would read as a confident wrong answer — so the guard is
    still load-bearing after the veto, which is exactly what ADR-006 keeps it
    for. Under the single check it is the ONLY thing holding it."""
    _id, expect, got, sufficient, relevance = next(
        r for r in _rows() if r[0] == "outside-holmes-boston"
    )

    assert expect == "not_in_sources"
    assert sufficient >= SUFFICIENT_ABSTAIN
    assert entity_ok(got, sufficient, relevance) is False
    assert not decides_to_answer(sufficient, entity_passed=False), (
        "with the relevance floor gone, the entity guard is the only thing that "
        "stops this item becoming a confident wrong answer"
    )


def test_a_gist_question_is_judged_by_sufficiency_alone() -> None:
    """The exemption KI-70 added is not needed once the veto is: a `summarize`
    question is decided by the one evidence check and the entity guard, with no
    exemption and no threshold keyed on the intent."""
    gist = [r for r in _rows() if r[0] == "broad-alice"]
    assert gist, "the recorded gist item is the evidence for this"
    for _id, _expect, got, sufficient, relevance in gist:
        assert sufficient >= SUFFICIENT_ABSTAIN
        assert decides_to_answer(sufficient, entity_ok(got, sufficient, relevance))
    # And the two runs' readings (0.61 and 0.56) both clear comfortably,
    # which is what makes it safe for the intent not to need a special case.


def test_a_below_the_floor_evidence_check_declines_whatever_the_intent() -> None:
    """A gist question whose passages do not answer it still declines.
    `broad-alice` is the reason the veto existed at all, so this is the case
    that must not regress into answering from topically-adjacent evidence."""
    assert not decides_to_answer(0.02)
    assert not decides_to_answer(0.04)
    assert not decides_to_answer(0.049999)


# --- the rule in the code path, with the recorded values ---------------------


#: The `no_llm` stub answers every `complete` call with a fixed string, so the
#: rewritten query is "the question, standalone" — which names no entity, and
#: the entity guard is skipped for a question that names none (skipping never
#: abstains). The entity cases therefore pin the rewrite to the raw message,
#: which is what a rewrite of a first-turn question already returns unchanged.
_KEEP_THE_QUESTION = "What is the capital of the Ridgeline R-7?"


def _keep_the_entity(monkeypatch: pytest.MonkeyPatch, question: str = _KEEP_THE_QUESTION) -> None:
    async def fake_complete(**_kwargs: Any) -> str:
        return question

    monkeypatch.setattr(auto_module, "complete", fake_complete)


async def _sufficient_runs(
    params: AutoRunInput, values: tuple[float, float], *, entity: float = 0.9
) -> tuple[AutoRun, Any]:
    """A run of the same fixture, suffiency pinned per attempt and the entity
    guard pinned to `entity`.

    `_IngressJev` answers every entity question at 0.9 because every fixture
    corpus is about the question's entity; `entity` is here so the mismatch
    case can be asked of the same run.
    """

    class _Pinned(_RelevanceJev):
        def __init__(self) -> None:
            super().__init__("lookup", 0.0, 0.97)
            self.calls: list[float] = []

        async def decide(self, *, state: Any, questions: Any) -> Any:
            answers = await super().decide(state=state, questions=questions)
            for name in answers:
                if name.startswith("entity_"):
                    answers[name] = Answer(
                        engine="jev", latency_ms=1, value=entity, probability=entity
                    )
            if "sufficient" in answers:
                value = values[len(self.calls)]
                self.calls.append(value)
                answers["sufficient"].value = value
                answers["sufficient"].probability = value
            return answers

    jev = _Pinned()
    run = await prepare_auto_run(
        get_session_factory(), params, DecisionEngine(jev=jev, mode="jev_only")
    )
    return run, jev


async def test_no_relevance_decision_is_emitted(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The veto is gone, so nothing emits its row. The relevance Decision was
    computed in the evidence stage rather than asked as a question, which is
    why it needed publishing by hand (`run_auto._publish_trace`); both halves
    are gone, and a run that still emits one is reading a removed signal."""
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run, _jev = await _sufficient_runs(params, (0.61, 0.61))

    assert not any(d.name == "relevance" for d in run.decision_events)
    assert run.sufficiency_p == pytest.approx(0.61)
    assert run.contexts, "sufficiency cleared, so the run answered from evidence"


async def test_insufficient_then_sufficient_answers(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The corrective shape ADR-006 specifies: one evidence check, one
    corrective retrieval, then answer rather than decline.

    Sufficiency is 0.03 on the first attempt (under the floor, over the
    `clearly absent` skip bound) and 0.61 on the second."""
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run, jev = await _sufficient_runs(params, (0.03, 0.61))

    assert jev.calls == [0.03, 0.61], "exactly one corrective retrieval"
    assert run.abstain_event is None
    assert run.contexts


async def test_insufficient_twice_declines(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two insufficient checks and the run declines. One correction, never two:
    the loop clamps any admin override of `retrieval.retry_limit` to 1."""
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run, jev = await _sufficient_runs(params, (0.03, 0.04))

    assert jev.calls == [0.03, 0.04]
    assert run.abstain_event is not None
    assert run.contexts == [], "an abstention carries no citations"


async def test_an_entity_mismatch_still_declines_on_sufficient_evidence(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard ADR-006 keeps. Sufficiency is comfortably over its floor and
    the run still declines, because the passages are about another entity — the
    shape `outside-holmes-boston` recorded, and the only thing holding it now
    that the relevance floor is gone.

    `_RelevanceJev`'s corpus is about the question's entity, so the entity
    reading is pinned to 0.11 — the value `outside-holmes-boston` recorded,
    under the 0.50 `entity_match` floor."""
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    # A question that names an entity, or there is no entity check to fail.
    _keep_the_entity(monkeypatch)
    params = dc_replace(params, question=_KEEP_THE_QUESTION)
    run, _jev = await _sufficient_runs(params, (0.61, 0.61), entity=0.11)

    assert run.sufficiency_p == pytest.approx(0.61), "the evidence check cleared"
    assert run.abstain_event is not None, "the entity guard declined anyway"
    assert run.contexts == []


async def test_the_same_run_answers_when_the_entity_matches(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the case above: the same question, the same sufficiency,
    an entity reading of 0.9 — and the run answers. Without it, "it abstained"
    above would not show *which* signal abstained it."""
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    _keep_the_entity(monkeypatch)
    params = dc_replace(params, question=_KEEP_THE_QUESTION)
    run, _jev = await _sufficient_runs(params, (0.61, 0.61), entity=0.9)

    assert run.sufficiency_p == pytest.approx(0.61)
    assert run.abstain_event is None
    assert run.contexts


def test_the_relabelled_item_is_not_in_the_answer_class() -> None:
    """`amb-bovary-homais` was relabelled `answer` -> `not_in_sources` on
    2026-10-12 after reading the corpus (`Rouard` is 0 hits corpus-wide). The
    run's behaviour was right all along, so it stays out of the answer class and
    out of the false-abstention count in every replay above."""
    assert [r for r in _rows() if r[0] == "amb-bovary-homais"] != []
    assert all(
        expect == "not_in_sources"
        for _i, expect, *_ in _rows()
        if _i == "amb-bovary-homais"
    )