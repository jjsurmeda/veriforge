"""The entity-mismatch verdict classifies a run from the summary's own fields.

Lane B2's probe nearly reported a false failure rate because it inferred
"answered" from the stream — and a decline streams a delta too, so every
correct decline counted as an answer. These cases pin the classification to
`failed` / `clean_declines` / `confident_wrong_answers`, including the case the
inference gets wrong in the other direction: an unclean (prose) decline is not
a confident wrong answer.
"""

from collections.abc import Mapping
from pathlib import Path

from evals import entity_gate
from evals.entity_gate import EXPECTED_ITEMS, entity_mismatch_failures


def _summary(**overrides: float | None) -> Mapping[str, float | None]:
    """A perfect run, with the named fields moved off perfect."""
    summary: dict[str, float | None] = {
        "items": float(EXPECTED_ITEMS),
        "scored": float(EXPECTED_ITEMS),
        "failed": 0.0,
        "should_abstain_total": float(EXPECTED_ITEMS),
        "clean_declines": float(EXPECTED_ITEMS),
        "unclean_declines": 0.0,
        "confident_wrong_answers": 0.0,
    }
    summary.update(overrides)
    return summary


def test_all_declined_passes() -> None:
    assert entity_mismatch_failures(_summary()) == []


def test_one_answered_confidently_fails() -> None:
    summary = _summary(
        clean_declines=11.0,
        unclean_declines=1.0,
        confident_wrong_answers=1.0,
    )

    failures = entity_mismatch_failures(summary)

    assert any("11 of 12 clean declines" in failure for failure in failures)
    assert any("1 confident wrong" in failure for failure in failures)


def test_one_unclean_decline_fails_without_calling_it_confident_wrong() -> None:
    """An item that replied "the sources don't cover that" with citations is a
    decline, not a confident wrong answer (PRD §5) — but it is not a *clean*
    one either, so the run still fails, on the count."""
    summary = _summary(clean_declines=11.0, unclean_declines=1.0)

    failures = entity_mismatch_failures(summary)

    assert any("11 of 12 clean declines" in failure for failure in failures)
    assert not any("confident wrong" in failure for failure in failures)


def test_one_errored_item_fails_as_an_error_not_a_decline() -> None:
    summary = _summary(
        items=12.0,
        scored=11.0,
        failed=1.0,
        should_abstain_total=11.0,
        clean_declines=11.0,
        unclean_declines=0.0,
    )

    failures = entity_mismatch_failures(summary)

    assert any("1 of 12 items errored" in failure for failure in failures)
    assert any("an errored item is not a decline" in failure for failure in failures)


def test_a_short_run_is_not_twelve_of_twelve() -> None:
    summary = _summary(
        items=11.0,
        scored=11.0,
        should_abstain_total=11.0,
        clean_declines=11.0,
    )

    failures = entity_mismatch_failures(summary)

    assert any("graded 11 items, not 12" in failure for failure in failures)


def test_a_missing_summary_file_is_not_a_pass(tmp_path: Path) -> None:
    """The run crashed before writing its summary, or never ran. Either way
    nothing was measured, and reporting a pass would be a green check on a
    green tree."""
    assert entity_gate.main(["entity_gate", str(tmp_path / "absent.json")]) == 1


def test_a_null_field_is_zero_not_a_pass() -> None:
    """A summary missing a count is unverified, and 'no confident wrong
    answers reported' must not read as 'none'."""
    summary = _summary(confident_wrong_answers=None, clean_declines=None)

    failures = entity_mismatch_failures(summary)

    assert any("0 of 12 clean declines" in failure for failure in failures)