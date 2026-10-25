"""The books-acceptance verdict classifies a run from the summary's own fields.

`make check-work` step 9 exists because the eval gate and entity-mismatch pass
without ever replaying `evals/acceptance/books.json`, which left KI-28 (a
should-decline question answered) and KI-56 (a real answer lost) unchecked. These
cases pin the PRD §5 classification to the counts `scripts.acceptance.summarise`
writes, so the gate cannot pass by scraping a printed table or by tolerating a
partial run.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from evals import acceptance_gate
from evals.acceptance_gate import (
    EXPECTED_COUNTS,
    acceptance_failures,
    max_false_abstentions,
    min_clean_declines,
)


def _summary(**overrides: Any) -> dict[str, Any]:
    """A passing whole-set run, with the named counts moved off passing."""
    summary: dict[str, Any] = {
        "counts": {
            "items": EXPECTED_COUNTS["items"],
            "answer_items": EXPECTED_COUNTS["answer_items"],
            "abstain_items": EXPECTED_COUNTS["abstain_items"],
            "smalltalk_items": EXPECTED_COUNTS["smalltalk_items"],
            "library_items": EXPECTED_COUNTS["library_items"],
            "clean_declines": EXPECTED_COUNTS["abstain_items"],
            "unclean_declines": 0,
            "confident_wrong": 0,
            "false_abstentions": 0,
            "uncited_answers": 0,
            "content_misses": 0,
            "errored": 0,
        },
        "detail": {
            "confident_wrong_ids": [],
            "clean_decline_ids": [],
            "unclean_decline_ids": [],
            "false_abstention_ids": [],
            "uncited_answer_ids": [],
            "content_miss_ids": [],
            "errored_ids": [],
            "failed_ids": [],
        },
        "served_commit": "a" * 40,
        "items": [],
    }
    for key, value in overrides.items():
        summary["counts"][key] = value
    return summary


def test_a_clean_run_passes() -> None:
    assert acceptance_failures(_summary()) == []


def test_one_confident_wrong_fails() -> None:
    """KI-28's shape: a should-decline item the run answered instead."""
    summary = _summary(confident_wrong=1, clean_declines=19)
    summary["detail"]["confident_wrong_ids"] = ["outside-study-in-scarlet"]

    failures = acceptance_failures(summary)

    assert any("1 confident wrong" in failure for failure in failures)
    assert any("outside-study-in-scarlet" in failure for failure in failures)


def test_seventeen_of_twenty_clean_declines_fails() -> None:
    """17/20 = 85%, under PRD §5's 90%."""
    summary = _summary(clean_declines=17, unclean_declines=3)
    summary["detail"]["unclean_decline_ids"] = ["a", "b", "c"]

    failures = acceptance_failures(summary)

    assert any("17 of 20 clean declines" in failure for failure in failures)
    assert any("at least 18" in failure for failure in failures)


def test_eighteen_of_twenty_clean_declines_passes() -> None:
    """The boundary: -(-20 * 90 // 100) = 18, so 18/20 = 90% passes."""
    assert acceptance_failures(_summary(clean_declines=18, unclean_declines=2)) == []


def test_an_unclean_decline_fails_on_the_count_not_as_confident_wrong() -> None:
    """A prose "the sources don't cover that" with citations is a decline (PRD §5),
    not a confident wrong answer — but it is not clean either."""
    summary = _summary(clean_declines=17, unclean_declines=3)

    failures = acceptance_failures(summary)

    assert any("clean declines" in failure for failure in failures)
    assert not any("confident wrong" in failure for failure in failures)


def test_two_of_thirty_two_false_abstentions_fails() -> None:
    """KI-56's shape: two real answers the run declined on."""
    summary = _summary(false_abstentions=2)
    summary["detail"]["false_abstention_ids"] = ["rp77-torque", "other"]

    failures = acceptance_failures(summary)

    assert any("2 of 32 answerable items declined" in failure for failure in failures)
    assert any("rp77-torque" in failure for failure in failures)


def test_one_of_thirty_three_false_abstentions_passes() -> None:
    """The boundary: 1/32 = 3%, under PRD §5's 5%."""
    assert acceptance_failures(_summary(false_abstentions=1)) == []


def test_one_errored_item_fails_as_an_error_not_a_decline() -> None:
    """An error inside the abstain class must not be scored as a decline."""
    summary = _summary(errored=1, clean_declines=19)
    summary["detail"]["errored_ids"] = ["ml-fr-outside"]

    failures = acceptance_failures(summary)

    assert any("1 item(s) errored" in failure for failure in failures)
    assert any("never a decline" in failure for failure in failures)


def test_an_uncited_answer_fails_even_when_the_text_is_right() -> None:
    """KI-71's bar line. `broad-sherlock`'s run cleared every other clause —
    20/20 clean declines, 0 confident wrong, 2 false abstentions of 32 — and
    still answered a content question from model memory with nothing behind
    it. The gate has to fail that, because the text being right is exactly
    what makes the shape hard to notice."""
    summary = _summary(uncited_answers=1)
    summary["detail"]["uncited_answer_ids"] = ["broad-sherlock"]

    failures = acceptance_failures(summary)

    assert any("1 answer-class item(s) completed with zero citations" in f for f in failures)
    assert any("broad-sherlock" in f for f in failures)


def test_an_uncited_answer_is_not_a_false_abstention() -> None:
    """The two counts are disjoint and the gate reports them apart: the run
    did not decline, so calling it a false abstention would describe the wrong
    behaviour as well as hide the right one."""
    summary = _summary(uncited_answers=1)
    summary["detail"]["uncited_answer_ids"] = ["broad-sherlock"]

    failures = acceptance_failures(summary)

    assert not any("false abstention" in f for f in failures)
    assert not any("confident wrong" in f for f in failures)


def test_two_content_misses_fail() -> None:
    """KI-75. Two answer-class items answered, cited the right book, and still
    did not state what the item asked for. Nothing above this line can see
    that: the run held decline accuracy, false abstention and citations."""
    summary = _summary(content_misses=2)
    summary["detail"]["content_miss_ids"] = ["plot-speckled-band", "broad-time-machine"]

    failures = acceptance_failures(summary)

    assert any("2 of 32 answerable items answered but did not state" in f for f in failures)
    assert any("plot-speckled-band" in f for f in failures)
    assert any("broad-time-machine" in f for f in failures)
    assert any("≤ 1 content miss" in f for f in failures)


def test_one_content_miss_passes() -> None:
    """The bar line: ≤ 1 of 32 answerables, the same arithmetic as the false
    abstention rate at this mix."""
    summary = _summary(content_misses=1)
    summary["detail"]["content_miss_ids"] = ["plot-speckled-band"]

    assert acceptance_failures(summary) == []


def test_a_content_miss_is_not_any_of_the_other_classes() -> None:
    """The three answer-class counts are disjoint and the gate reports them
    apart. A cited, non-declining reply is not an abstention, not an uncited
    answer, and (for an answer-class item) not a confident wrong — calling it
    any of those hides the one that is true."""
    summary = _summary(content_misses=1)
    summary["detail"]["content_miss_ids"] = ["plot-speckled-band"]

    failures = acceptance_failures(summary)

    assert not any("false abstention" in f for f in failures)
    assert not any("uncited" in f for f in failures)
    assert not any("confident wrong" in f for f in failures)


def test_a_failed_smalltalk_item_fails() -> None:
    summary = _summary()
    summary["detail"]["failed_ids"] = ["smalltalk-hi"]
    summary["items"] = [{"id": "smalltalk-hi", "expect": "smalltalk"}]

    failures = acceptance_failures(summary)

    assert any("smalltalk" in failure and "smalltalk-hi" in failure for failure in failures)


def test_a_failed_library_item_fails() -> None:
    summary = _summary()
    summary["detail"]["failed_ids"] = ["library-count"]
    summary["items"] = [{"id": "library-count", "expect": "library"}]

    failures = acceptance_failures(summary)

    assert any("library" in failure and "library-count" in failure for failure in failures)


def test_a_filtered_run_is_not_a_whole_set_verdict(tmp_path: Path) -> None:
    """`acceptance.py id1,id2` is for fixing a failing item, not for a verdict.
    A short summary must not pass, or the gate can be green on four items."""
    summary = _summary(items=4, answer_items=4, abstain_items=0, smalltalk_items=0, library_items=0)

    failures = acceptance_failures(summary)

    assert any("graded 4 items, not 56" in failure for failure in failures)


def test_a_missing_count_does_not_read_as_zero_of_everything() -> None:
    """A summary with no counts block is not a perfect run."""
    failures = acceptance_failures({"served_commit": "a" * 40})

    assert failures
    assert any("graded 0 items, not 56" in failure for failure in failures)


def test_the_bar_arithmetic_does_not_drift_on_float_error() -> None:
    """`math.ceil(20 * 0.90)` is 19, because 0.9 is inexact. The rate must not
    tighten itself by an item through a rounding accident."""
    assert min_clean_declines(20) == 18
    assert min_clean_declines(21) == 19
    assert max_false_abstentions(32) == 1
    assert max_false_abstentions(33) == 1
    assert max_false_abstentions(100) == 5


def test_a_missing_summary_file_is_not_a_pass(tmp_path: Path) -> None:
    assert acceptance_gate.main(["acceptance_gate", str(tmp_path / "absent.json")]) == 1


def test_a_summary_with_no_served_commit_does_not_crash_the_gate(tmp_path: Path) -> None:
    """The counts still classify; the step (not this function) compares the
    served commit with HEAD, because only the step knows what HEAD is."""
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary()))

    assert acceptance_gate.main(["acceptance_gate", str(path)]) == 0


@pytest.mark.parametrize("argv", [[], ["acceptance_gate"], ["a", "b", "c"]])
def test_usage_error_when_the_summary_path_is_wrong(argv: list[str]) -> None:
    """`main` takes the program name plus exactly one path. Two extra words is a
    caller mistake, not a file it should guess at."""
    assert acceptance_gate.main(argv) == 2


def test_the_expected_counts_are_the_relabelled_set() -> None:
    """Pinned so a set edit that changes the mix has to change the bar in the
    same commit, rather than silently passing against a stale expectation.
    32/21, not 33/20: `amb-bovary-homais` moved to `not_in_sources` on
    2026-10-12 (phase 1c item 2) because its premise is not in this corpus.
    Back to 33/20 on 2026-10-17 (ADR-006): `ml-zh-xiyou-nezha` moved the
    other way — the corpus states the Heavenly King lives in the Cloud
    Tower Palace and calls Nezha there. 32/20 (56 items) from 2026-10-22
    (KI-80): `outside-whitman` was removed, its only passage says a
    distinction exists but not what it is."""
    assert EXPECTED_COUNTS == {
        "items": 56,
        "answer_items": 32,
        "abstain_items": 20,
        "smalltalk_items": 2,
        "library_items": 2,
    }


def test_the_set_file_agrees_with_the_pinned_counts() -> None:
    """The pin above is a literal; this is the one that would catch it going
    stale. Read the committed set rather than trusting the constant to describe
    it, so a relabel that forgets the gate fails here rather than at 03:00 in a
    gate run."""
    from collections import Counter

    path = Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json"
    items = json.loads(path.read_text())["items"]
    counts = Counter(str(item["expect"]) for item in items)

    assert len(items) == EXPECTED_COUNTS["items"]
    assert counts["answer"] == EXPECTED_COUNTS["answer_items"]
    assert counts["not_in_sources"] == EXPECTED_COUNTS["abstain_items"]
    assert counts["smalltalk"] == EXPECTED_COUNTS["smalltalk_items"]
    assert counts["library"] == EXPECTED_COUNTS["library_items"]


def test_every_item_id_in_the_set_is_unique() -> None:
    """A duplicate id would make `detail`'s id lists point at two different
    items at once, and `failed_ids` would name one of them twice."""
    path = Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json"
    ids = [str(item["id"]) for item in json.loads(path.read_text())["items"]]

    assert len(ids) == len(set(ids))


# --- the held-out set has its own verdict (third-party review #4) -----------


def _heldout_summary(**overrides: Any) -> dict[str, Any]:
    summary = _summary()
    counts = acceptance_gate.HELDOUT_COUNTS
    summary["counts"].update(
        {
            "items": counts["items"],
            "answer_items": counts["answer_items"],
            "abstain_items": counts["abstain_items"],
            "smalltalk_items": 0,
            "library_items": 0,
            "clean_declines": counts["abstain_items"],
        }
    )
    summary["counts"].update(overrides)
    return summary


def test_a_clean_heldout_run_passes_its_own_gate_and_fails_the_books_gate() -> None:
    assert acceptance_failures(_heldout_summary(), "heldout") == []
    assert acceptance_failures(_heldout_summary(), "books"), "wrong mix for the books set"


def test_the_heldout_bar_is_zero_confident_wrong_and_at_most_one_false_abstention() -> None:
    wrong = acceptance_failures(_heldout_summary(confident_wrong=1), "heldout")
    assert any("confident wrong" in f for f in wrong)
    assert acceptance_failures(_heldout_summary(false_abstentions=1), "heldout") == []
    two = acceptance_failures(_heldout_summary(false_abstentions=2), "heldout")
    assert any("answerable items declined" in f for f in two)


def test_a_filtered_heldout_run_is_not_a_whole_set_verdict() -> None:
    failures = acceptance_failures(_heldout_summary(items=5), "heldout")
    assert any("not a whole-set measurement" in f for f in failures)


def test_clean_declines_are_reported_not_gated_for_the_heldout_set() -> None:
    assert acceptance_failures(_heldout_summary(clean_declines=5), "heldout") == []


# --------------------------------------------------------------------------
# The Deep set (R2b item 2): its own bar — 0 confident wrong, ≤ 1 content
# miss, errored fails, pinned counts, p50 wall clock ≤ 45 s; declines,
# false abstentions and uncited answers are reported, not gated.
# --------------------------------------------------------------------------


def _deep_summary(**overrides: Any) -> dict[str, Any]:
    from evals.acceptance_gate import DEEP_COUNTS

    summary: dict[str, Any] = {
        "counts": {
            "items": DEEP_COUNTS["items"],
            "answer_items": DEEP_COUNTS["answer_items"],
            "abstain_items": DEEP_COUNTS["abstain_items"],
            "smalltalk_items": 0,
            "library_items": 0,
            "clean_declines": DEEP_COUNTS["abstain_items"],
            "unclean_declines": 0,
            "confident_wrong": 0,
            "false_abstentions": 0,
            "uncited_answers": 0,
            "content_misses": 0,
            "errored": 0,
        },
        "p50_total_ms": 18_000,
        "detail": {
            "confident_wrong_ids": [],
            "clean_decline_ids": [],
            "unclean_decline_ids": [],
            "false_abstention_ids": [],
            "uncited_answer_ids": [],
            "content_miss_ids": [],
            "errored_ids": [],
            "failed_ids": [],
        },
        "served_commit": "a" * 40,
        "items": [],
    }
    for key, value in overrides.items():
        if key in summary.get("counts", {}):
            summary["counts"][key] = value
        else:
            summary[key] = value
    return summary


def test_a_clean_deep_run_passes() -> None:
    assert acceptance_failures(_deep_summary(), "deep") == []


def test_one_confident_wrong_fails_on_the_deep_set() -> None:
    summary = _deep_summary(confident_wrong=1)
    summary["detail"]["confident_wrong_ids"] = ["deep-sherlock-eurus"]
    failures = acceptance_failures(summary, "deep")
    assert failures and any("confident wrong" in f for f in failures)


def test_one_content_miss_passes_and_two_fail_on_the_deep_set() -> None:
    assert acceptance_failures(_deep_summary(content_misses=1), "deep") == []
    failures = acceptance_failures(_deep_summary(content_misses=2), "deep")
    assert any("content miss" in f for f in failures)


def test_a_slow_deep_median_fails_and_the_bar_edge_passes() -> None:
    assert acceptance_failures(_deep_summary(p50_total_ms=45_000), "deep") == []
    failures = acceptance_failures(_deep_summary(p50_total_ms=45_001), "deep")
    assert any("45" in f or "wall clock" in f for f in failures)


def test_no_p50_at_all_fails_the_deep_bar() -> None:
    """A summary without `p50_total_ms` was produced by an old runner, not by
    a fast one: absent is not a pass."""
    summary = _deep_summary()
    del summary["p50_total_ms"]
    failures = acceptance_failures(summary, "deep")
    assert any("p50_total_ms" in f for f in failures)


def test_a_filtered_deep_run_is_not_a_whole_set_verdict() -> None:
    failures = acceptance_failures(_deep_summary(items=13), "deep")
    assert any("whole-set measurement" in f for f in failures)


def test_an_errored_deep_item_fails_as_an_error() -> None:
    summary = _deep_summary(errored=1)
    summary["detail"]["errored_ids"] = ["deep-alice-first-changes"]
    failures = acceptance_failures(summary, "deep")
    assert any("errored" in f for f in failures)


def test_declines_and_false_abstentions_are_reported_not_gated_on_the_deep_set() -> None:
    """R2b's bar for Deep: the decline classes are report content, not pass
    conditions — one false abstention of 10 and two unclean declines stay a
    pass until a different clause names the same behaviour."""
    summary = _deep_summary(false_abstentions=1, unclean_declines=1, clean_declines=3)
    summary["detail"]["false_abstention_ids"] = ["deep-bovary-emma-poison"]
    summary["detail"]["unclean_decline_ids"] = ["deep-sherlock-eurus"]
    assert acceptance_failures(summary, "deep") == []


def test_the_deep_bar_does_not_gate_an_uncited_answer() -> None:
    """R2b's brief names the clauses it gates for Deep and deliberately leaves
    the uncited-answer count to the report. Pinned so a later phase cannot
    add the clause silently without touching this pin first."""
    summary = _deep_summary(uncited_answers=1)
    summary["detail"]["uncited_answer_ids"] = ["deep-noli-ibarra-project"]
    assert acceptance_failures(summary, "deep") == []


def test_the_category_report_counts_passes_per_category() -> None:
    summary = {"items": [{"id": "a", "pass": True}, {"id": "b", "pass": False}, {"id": "c"}]}
    lines = acceptance_gate.category_report(summary, {"a": "lookup", "b": "lookup", "c": "gist"})
    assert lines == ["  gist: 0/1", "  lookup: 1/2"]


# --------------------------------------------------------------------------
# The frozen Deep splits (deep_test 16/10/6, deep_heldout 8/4/4): same Deep
# bar as "deep", their own pinned counts.
# --------------------------------------------------------------------------

_SPLITS = [
    ("deep_test", acceptance_gate.DEEP_TEST_COUNTS),
    ("deep_heldout", acceptance_gate.DEEP_HELDOUT_COUNTS),
]


def _split_summary(counts: dict[str, int], **overrides: Any) -> dict[str, Any]:
    summary = _deep_summary(**overrides)
    summary["counts"]["items"] = overrides.get("items", counts["items"])
    summary["counts"]["answer_items"] = counts["answer_items"]
    summary["counts"]["abstain_items"] = counts["abstain_items"]
    summary["counts"]["clean_declines"] = counts["abstain_items"]
    return summary


def test_the_deep_split_sizes_are_pinned() -> None:
    assert acceptance_gate.DEEP_TEST_COUNTS["items"] == 16
    assert acceptance_gate.DEEP_TEST_COUNTS["answer_items"] == 10
    assert acceptance_gate.DEEP_TEST_COUNTS["abstain_items"] == 6
    assert acceptance_gate.DEEP_HELDOUT_COUNTS["items"] == 8
    assert acceptance_gate.DEEP_HELDOUT_COUNTS["answer_items"] == 4
    assert acceptance_gate.DEEP_HELDOUT_COUNTS["abstain_items"] == 4


@pytest.mark.parametrize(("set_name", "counts"), _SPLITS)
def test_a_clean_run_of_each_deep_split_passes(set_name: str, counts: dict[str, int]) -> None:
    assert acceptance_failures(_split_summary(counts), set_name) == []


@pytest.mark.parametrize(("set_name", "counts"), _SPLITS)
def test_each_deep_split_is_judged_by_the_deep_bar(set_name: str, counts: dict[str, int]) -> None:
    # False abstentions are reported, not gated; a confident wrong, a slow p50
    # and a filtered run still fail.
    assert acceptance_failures(_split_summary(counts, false_abstentions=1), set_name) == []
    wrong = acceptance_failures(_split_summary(counts, confident_wrong=1), set_name)
    assert any("confident wrong" in f for f in wrong)
    slow = acceptance_failures(_split_summary(counts, p50_total_ms=45_001), set_name)
    assert any("wall clock" in f for f in slow)
    filtered = acceptance_failures(_split_summary(counts, items=counts["items"] - 1), set_name)
    assert any("whole-set measurement" in f for f in filtered)


def test_one_deep_split_summary_is_not_the_other_splits_verdict() -> None:
    failures = acceptance_failures(_split_summary(acceptance_gate.DEEP_HELDOUT_COUNTS), "deep_test")
    assert any("whole-set measurement" in f for f in failures)
