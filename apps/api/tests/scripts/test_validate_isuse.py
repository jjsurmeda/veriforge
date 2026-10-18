"""The IsUse validation set is well formed and its scoring does what the bar says."""

import json
from pathlib import Path

from scripts.validate_isuse import MAX_NON_ANSWERS_PASSED, TRIPLES, score

TRIPLE_LIST = json.loads(Path(TRIPLES).read_text())


def test_the_set_is_sixty_triples_split_evenly_with_sources() -> None:
    assert len(TRIPLE_LIST) == 60
    assert sum(t["label"] == "answers" for t in TRIPLE_LIST) == 30
    assert sum(t["label"] == "does_not_answer" for t in TRIPLE_LIST) == 30
    assert all(t["question"] and t["answer"] and t["sources"] for t in TRIPLE_LIST)
    assert len({t["id"] for t in TRIPLE_LIST}) == 60


def test_a_non_answer_that_clears_the_floor_counts_against_the_bar() -> None:
    values: dict[str, float | None] = {
        t["id"]: 0.9 if t["label"] == "answers" else 0.1 for t in TRIPLE_LIST
    }
    perfect = score(TRIPLE_LIST, values, 0.47)
    assert perfect["bar_ok"] and perfect["answers_rejected"] == []

    wrong = next(t["id"] for t in TRIPLE_LIST if t["label"] == "does_not_answer")
    values[wrong] = 0.8
    one = score(TRIPLE_LIST, values, 0.47)
    assert one["non_answers_passed"] == [wrong]
    assert one["non_answers_passed_rate"] == 1 / 30 <= MAX_NON_ANSWERS_PASSED


def test_two_wrong_passes_break_the_bar_and_an_outage_fails_closed() -> None:
    values: dict[str, float | None] = {
        t["id"]: 0.9 if t["label"] == "answers" else 0.1 for t in TRIPLE_LIST
    }
    for wrong in [t["id"] for t in TRIPLE_LIST if t["label"] == "does_not_answer"][:2]:
        values[wrong] = 0.8
    assert not score(TRIPLE_LIST, values, 0.47)["bar_ok"]

    answer = next(t["id"] for t in TRIPLE_LIST if t["label"] == "answers")
    values[answer] = None
    assert answer in score(TRIPLE_LIST, values, 0.47)["answers_rejected"]


def _clean_values() -> dict[str, float | None]:
    return {t["id"]: 0.9 if t["label"] == "answers" else 0.1 for t in TRIPLE_LIST}


def test_every_call_failing_never_passes_the_bar() -> None:
    values: dict[str, float | None] = {t["id"]: None for t in TRIPLE_LIST}
    report = score(TRIPLE_LIST, values, 0.47)
    assert not report["bar_ok"]
    assert report["measured"] == 0 and report["coverage"] == 0.0
    assert report["errors"] == [t["id"] for t in TRIPLE_LIST]
    assert report["non_answers_passed_rate"] == 0.0


def test_one_error_in_sixty_still_evaluates_normally() -> None:
    values = _clean_values()
    error = TRIPLE_LIST[0]["id"]
    values[error] = None
    report = score(TRIPLE_LIST, values, 0.47)
    assert report["errors"] == [error]
    assert report["measured"] == 59 and report["coverage"] == 59 / 60 >= 0.95
    assert report["bar_ok"]


def test_ten_errors_fail_the_bar_with_no_wrong_passes() -> None:
    values = _clean_values()
    for t in TRIPLE_LIST[:10]:
        values[t["id"]] = None
    report = score(TRIPLE_LIST, values, 0.47)
    assert report["non_answers_passed"] == []
    assert len(report["errors"]) == 10 and report["coverage"] == 50 / 60
    assert not report["bar_ok"]
