"""Tests for the per-corpus runner summary (P1b item 5).

PRD §5's rows that the rollup has to make measurable: minimum claim support,
decline accuracy, false abstention, and the confident-wrong answer. Each one
is pinned here because each is a *count of events* rather than a mean, which
is exactly the kind of figure a refactor silently redefines.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.abstention import is_confident_wrong
from evals.runner import (
    MIN_SUPPORT_FLOOR,
    aggregate,
    aggregate_by_corpus,
    corpus_key,
    item_ids_for_gate_subset,
)


def item(
    *,
    should_abstain: bool = False,
    corpus: str | None = "aw-2000",
) -> Any:
    return SimpleNamespace(should_abstain=should_abstain, corpus=corpus, question="q")


def result(
    *,
    faithfulness: float | None = 1.0,
    min_support: float | None = 1.0,
    abstained: bool = False,
    answer: str = "an answer",
    context_recall: float | None = None,
    error: str | None = None,
    latency_ms: int = 100,
    stage_ms: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        error=error,
        faithfulness=faithfulness,
        min_support=min_support,
        abstained=abstained,
        answer=answer,
        context_recall=context_recall,
        latency_ms=latency_ms,
        stage_ms=stage_ms,
    )


# --------------------------------------------------------------------------
# min_support (PRD §5: >= 0.6 on >= 95% of answers)
# --------------------------------------------------------------------------


def test_min_support_share_counts_answers_over_the_floor() -> None:
    rows = [
        (item(), result(min_support=0.9)),
        (item(), result(min_support=MIN_SUPPORT_FLOOR)),  # the floor itself passes
        (item(), result(min_support=0.2)),
    ]
    summary = aggregate(rows)
    assert summary["min_support_share"] == pytest.approx(2 / 3)
    assert summary["answers_total"] == 3.0
    assert summary["answers_with_min_support"] == 3.0


def test_min_support_share_is_null_with_no_measured_answers() -> None:
    """Null, not 0.0: "no answer was reviewed" is not "every answer failed"."""
    summary = aggregate([(item(), result(min_support=None))])
    assert summary["min_support_share"] is None
    assert summary["answers_total"] == 0.0


def test_an_abstention_is_not_counted_towards_the_support_share() -> None:
    """An abstention scores min_support 1.0 in the column. Counting that here
    would pad the share with items that were never answered — which is how a
    run that declined everything could satisfy a grounding target."""
    rows = [
        (item(), result(min_support=0.1)),  # one real, failing answer
        (item(should_abstain=True), result(min_support=1.0, abstained=True)),
    ]
    summary = aggregate(rows)
    assert summary["answers_total"] == 1.0
    assert summary["min_support_share"] == 0.0


# --------------------------------------------------------------------------
# confident wrong answers (PRD §5: <= 1 per 100, and no item twice)
# --------------------------------------------------------------------------


def test_asserting_an_answer_to_a_should_abstain_item_is_confident_wrong() -> None:
    rows = [(item(should_abstain=True), result(abstained=False, answer="The capital is Canberra."))]
    assert aggregate(rows)["confident_wrong_answers"] == 1.0


def test_saying_the_sources_lack_it_is_a_decline_not_a_confident_wrong() -> None:
    rows = [
        (
            item(should_abstain=True),
            result(abstained=False, answer="I can't find that in the sources you have."),
        )
    ]
    summary = aggregate(rows)
    assert summary["confident_wrong_answers"] == 0.0
    # ...and it is an *unclean* decline, which is what decline accuracy counts.
    assert summary["clean_declines"] == 0.0
    assert summary["unclean_declines"] == 1.0


def test_a_real_abstention_is_a_clean_decline() -> None:
    rows = [(item(should_abstain=True), result(abstained=True, answer=""))]
    summary = aggregate(rows)
    assert summary["confident_wrong_answers"] == 0.0
    assert summary["clean_declines"] == 1.0
    assert summary["unclean_declines"] == 0.0


def test_is_confident_wrong_is_tested_both_ways_on_the_same_answer() -> None:
    """The abstention signal is authoritative. The same text is not a
    confident wrong answer when the graph abstained, and is one when it did
    not — so the test below is a pair, not a single case."""
    assert not is_confident_wrong(abstained=True, answer="Canberra.", citation_count=0)
    assert is_confident_wrong(abstained=False, answer="Canberra.", citation_count=0)
    # Citations do not change it: saying the sources lack it while citing
    # passages is an unclean decline, not an assertion.
    assert not is_confident_wrong(abstained=False, answer="Not in your sources.", citation_count=3)


def test_confident_wrong_is_only_counted_on_should_abstain_items() -> None:
    rows = [
        (item(should_abstain=False), result(abstained=False, answer="Canberra.")),
        (item(should_abstain=False), result(abstained=False, answer="Also an answer.")),
    ]
    assert aggregate(rows)["confident_wrong_answers"] == 0.0


# --------------------------------------------------------------------------
# false abstention / decline accuracy
# --------------------------------------------------------------------------


def test_false_abstention_counts_answerable_items_that_declined() -> None:
    rows = [
        (item(should_abstain=False), result(abstained=False)),
        (item(should_abstain=False), result(abstained=True)),
    ]
    summary = aggregate(rows)
    assert summary["false_abstention_rate"] == pytest.approx(0.5)
    assert summary["answerable_total"] == 2.0


def test_decline_accuracy_denominator_is_should_abstain_items_only() -> None:
    rows = [
        (item(should_abstain=True), result(abstained=True)),
        (item(should_abstain=True), result(abstained=True)),
        (item(should_abstain=False), result(abstained=False)),
    ]
    summary = aggregate(rows)
    assert summary["should_abstain_item_runs"] == 2.0
    assert summary["should_abstain_correct"] == 2.0
    assert summary["abstention_accuracy"] == pytest.approx(1.0)


def test_an_errored_item_is_excluded_from_every_rate() -> None:
    """A failed item was never measured. Counting it as a non-decline would
    report a database outage as a decline-accuracy regression."""
    rows = [
        (item(should_abstain=True), result(abstained=True)),
        (item(should_abstain=True), result(abstained=False, error="TimeoutError")),
    ]
    summary = aggregate(rows)
    assert summary["should_abstain_item_runs"] == 1.0
    assert summary["abstention_accuracy"] == pytest.approx(1.0)
    assert summary["failed"] == 1.0


# --------------------------------------------------------------------------
# per-corpus
# --------------------------------------------------------------------------


def test_summary_is_split_per_corpus() -> None:
    rows = [
        (item(corpus="books"), result(faithfulness=0.5)),
        (item(corpus="books"), result(faithfulness=1.0)),
        (item(corpus="manuals"), result(faithfulness=0.9)),
    ]
    per_corpus = aggregate_by_corpus(rows)
    assert set(per_corpus) == {"books", "manuals"}
    assert per_corpus["books"]["faithfulness"] == pytest.approx(0.75)
    assert per_corpus["manuals"]["faithfulness"] == pytest.approx(0.9)


def test_an_item_with_no_corpus_is_reported_not_hidden() -> None:
    """The rows predate the column. Folding them into a real corpus would
    make that corpus's number mean something other than what it says."""
    assert corpus_key(item(corpus=None)) == "unassigned"
    per_corpus = aggregate_by_corpus([(item(corpus=None), result())])
    assert set(per_corpus) == {"unassigned"}


def test_per_corpus_numbers_do_not_agree_with_the_run_wide_mean() -> None:
    """Pins that the two are different views, not one view twice: with one
    corpus at 0.5 and one at 1.0, the run mean is 0.75 and neither corpus is."""
    rows = [
        (item(corpus="a"), result(faithfulness=0.5)),
        (item(corpus="a"), result(faithfulness=0.5)),
        (item(corpus="b"), result(faithfulness=1.0)),
    ]
    assert aggregate(rows)["faithfulness"] == pytest.approx(2 / 3)
    assert aggregate_by_corpus(rows)["a"]["faithfulness"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# gate subsets (defined here, wired into the gate in Phase 2)
# --------------------------------------------------------------------------


def test_gate_subset_is_read_from_the_set_file() -> None:
    payload: dict[str, Any] = {"gate_subsets": {"aw-2000": ["lookup-01", "abstain-01"]}}
    assert item_ids_for_gate_subset(payload, "aw-2000") == ["lookup-01", "abstain-01"]


@pytest.mark.parametrize("payload", [{}, {"gate_subsets": {}}, {"gate_subsets": {"aw-2000": []}}])
def test_an_absent_or_empty_gate_subset_is_an_error(payload: dict[str, Any]) -> None:
    """ "No subset" and "a subset of nothing" must not look the same to
    whatever wires this in: both are a stop, not an empty run."""
    with pytest.raises(SystemExit):
        item_ids_for_gate_subset(payload, "aw-2000")


def test_the_seed_set_carries_a_corpus_and_a_stratified_subset() -> None:
    """The subset must actually be stratified: a gate over ten items drawn
    from one category cannot see a regression in any other."""
    set_file = Path(__file__).resolve().parents[4] / "evals" / "seed" / "items.json"
    payload = json.loads(set_file.read_text(encoding="utf-8"))
    subsets = payload["gate_subsets"]
    assert set(subsets) == {"aw-2000"}
    ids = subsets["aw-2000"]
    assert 8 <= len(ids) <= 12, ids
    by_id = {item_["id"]: item_ for item_ in payload["items"]}
    assert set(ids) <= set(by_id), "a subset id names no item"
    categories = {by_id[item_id]["category"] for item_id in ids}
    assert "should_abstain" in categories
    assert len(categories) >= 4, f"subset is not stratified: {categories}"
    # Both classes are in it, or a gate subset cannot see abstention at all.
    assert any(by_id[item_id]["should_abstain"] for item_id in ids)
    assert any(not by_id[item_id]["should_abstain"] for item_id in ids)
    # Every item declares the corpus the subset is drawn from.
    assert {item_["corpus"] for item_ in payload["items"]} == {"aw-2000"}


def test_the_gate_subset_is_not_the_fast20_subset() -> None:
    """They are different jobs — fast20 is the regression check, the per-corpus
    subset is the per-corpus sample — and a subset that quietly equals fast20
    would mean only one of the two exists."""
    set_file = Path(__file__).resolve().parents[4] / "evals" / "seed" / "items.json"
    payload = json.loads(set_file.read_text(encoding="utf-8"))
    assert set(payload["gate_subsets"]["aw-2000"]) != set(payload["fast20_ids"])


# --------------------------------------------------------------------------
# corpus fields and per-corpus gate subsets across all three set files
# --------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[4]
_SET_FILES = (
    _ROOT / "evals" / "seed" / "items.json",
    _ROOT / "evals" / "counterfactual" / "items.json",
    _ROOT / "evals" / "acceptance" / "books.json",
)


def test_every_item_of_every_set_carries_its_corpus() -> None:
    """Without a per-item corpus the rollup cannot bucket the set, and the
    PRD §5 table has a row per corpus (KI: the Phase 1 report's blocker 1)."""
    for set_file in _SET_FILES:
        payload = json.loads(set_file.read_text(encoding="utf-8"))
        missing = [row["id"] for row in payload["items"] if not row.get("corpus")]
        assert not missing, f"{set_file}: items without corpus: {missing[:5]}"
        corpora = {row["corpus"] for row in payload["items"]}
        assert len(corpora) == 1, f"{set_file}: one set should be one corpus, got {corpora}"


def test_the_rollup_buckets_every_item_of_every_set() -> None:
    """Post-migration, no row may fall into the `unassigned` bucket — that
    bucket is the report of a missing field, not a corpus."""
    for set_file in _SET_FILES:
        payload = json.loads(set_file.read_text(encoding="utf-8"))
        rows: list[tuple[Any, Any]] = []
        for row in payload["items"]:
            rows.append(
                (
                    SimpleNamespace(
                        should_abstain=row.get("should_abstain") or row.get("expect") != "answer",
                        corpus=row["corpus"],
                        question=row.get("question") or (row.get("turns") or [""])[0],
                    ),
                    SimpleNamespace(
                        error=None, faithfulness=1.0, min_support=1.0, abstained=False,
                        answer="a", context_recall=None, latency_ms=1, stage_ms=None,
                    ),
                )
            )
        bucketed = aggregate_by_corpus(rows)
        assert "unassigned" not in bucketed
        assert sum(int(b["items"] or 0) for b in bucketed.values()) == len(rows)


def test_counterfactual_gate_subset_is_stratified() -> None:
    set_file = _ROOT / "evals" / "counterfactual" / "items.json"
    payload = json.loads(set_file.read_text(encoding="utf-8"))
    ids = payload["gate_subsets"]["counterfactual"]
    assert 8 <= len(ids) <= 12, ids
    by_id = {row["id"]: row for row in payload["items"]}
    assert set(ids) <= set(by_id)
    categories = {by_id[i]["category"] for i in ids}
    assert len(categories) >= 3, categories
    assert "table_lookup" in categories and "multihop" in categories
    expects = {by_id[i]["expect"] for i in ids}
    assert expects == {"answer", "not_in_sources"}, expects
    assert {by_id[i]["corpus"] for i in ids} == {"counterfactual"}


def test_books_gate_subset_is_stratified() -> None:
    set_file = _ROOT / "evals" / "acceptance" / "books.json"
    payload = json.loads(set_file.read_text(encoding="utf-8"))
    ids = payload["gate_subsets"]["books"]
    assert 8 <= len(ids) <= 12, ids
    by_id = {row["id"]: row for row in payload["items"]}
    assert set(ids) <= set(by_id)
    expects = {by_id[i]["expect"] for i in ids}
    assert "answer" in expects and "not_in_sources" in expects, expects
    assert {by_id[i]["corpus"] for i in ids} == {"books"}
