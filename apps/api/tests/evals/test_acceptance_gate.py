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
            "errored": 0,
        },
        "detail": {
            "confident_wrong_ids": [],
            "clean_decline_ids": [],
            "unclean_decline_ids": [],
            "false_abstention_ids": [],
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
    """The boundary: 18/20 = exactly 90%, so it passes."""
    assert acceptance_failures(_summary(clean_declines=18, unclean_declines=2)) == []


def test_an_unclean_decline_fails_on_the_count_not_as_confident_wrong() -> None:
    """A prose "the sources don't cover that" with citations is a decline (PRD §5),
    not a confident wrong answer — but it is not clean either."""
    summary = _summary(clean_declines=17, unclean_declines=3)

    failures = acceptance_failures(summary)

    assert any("clean declines" in failure for failure in failures)
    assert not any("confident wrong" in failure for failure in failures)


def test_two_of_thirty_three_false_abstentions_fails() -> None:
    """KI-56's shape: two real answers the run declined on."""
    summary = _summary(false_abstentions=2)
    summary["detail"]["false_abstention_ids"] = ["rp77-torque", "other"]

    failures = acceptance_failures(summary)

    assert any("2 of 33 answerable items declined" in failure for failure in failures)
    assert any("rp77-torque" in failure for failure in failures)


def test_one_of_thirty_three_false_abstentions_passes() -> None:
    """The boundary: 1/33 = 3%, under PRD §5's 5%."""
    assert acceptance_failures(_summary(false_abstentions=1)) == []


def test_one_errored_item_fails_as_an_error_not_a_decline() -> None:
    """An error inside the abstain class must not be scored as a decline."""
    summary = _summary(errored=1, clean_declines=19)
    summary["detail"]["errored_ids"] = ["ml-fr-outside"]

    failures = acceptance_failures(summary)

    assert any("1 item(s) errored" in failure for failure in failures)
    assert any("never a decline" in failure for failure in failures)


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

    assert any("graded 4 items, not 57" in failure for failure in failures)


def test_a_missing_count_does_not_read_as_zero_of_everything() -> None:
    """A summary with no counts block is not a perfect run."""
    failures = acceptance_failures({"served_commit": "a" * 40})

    assert failures
    assert any("graded 0 items, not 57" in failure for failure in failures)


def test_the_bar_arithmetic_does_not_drift_on_float_error() -> None:
    """`math.ceil(20 * 0.90)` is 19, because 0.9 is inexact. The rate must not
    tighten itself by an item through a rounding accident."""
    assert min_clean_declines(20) == 18
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


def test_the_expected_counts_are_the_widened_set() -> None:
    """Pinned so a set edit that changes the mix has to change the bar in the
    same commit, rather than silently passing against a stale expectation."""
    assert EXPECTED_COUNTS == {
        "items": 57,
        "answer_items": 33,
        "abstain_items": 20,
        "smalltalk_items": 2,
        "library_items": 2,
    }