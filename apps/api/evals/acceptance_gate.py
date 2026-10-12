"""Verdict for the books acceptance set (phase 1b, `make check-work` step 9).

The eval gate and the entity-mismatch set both pass today without ever
replaying `evals/acceptance/books.json`, which has not run since 2026-10-01 —
so KI-28 (a should-decline question answered) and KI-56 (a real answer lost)
were not checked by anything. This is the pass/fail for that set, from the
numbers PRD §5 states for one run:

- **0 confident wrong.** A should-decline item whose reply asserts an answer
  (the scorer's `says_not_in_sources` false) fails. PRD §5's own bar is ≤1 per
  100 item-runs; on a 20-item class that is 0, and the brief takes 0.
- **Clean declines ≥ 90%** of should-decline items — 18 of 20. A prose "not in
  the sources" reply with citations is an unclean decline and counts against
  this, not against confident wrong.
- **False abstention ≤ 5%** of answerable items — 1 of 33.
- **An `answer`-class item that completed with zero citations fails**, whether
  its text was right or wrong. This is KI-71: ingress can classify a content
  question as `chitchat`, the run skips retrieval and answers from model
  memory, and every other clause above passes — a correct, warm, uncited
  reply is the failure shape this product exists not to ship. Answering a
  content question from memory is the one thing the product says it doesn't
  do, so the bar is a count like the others, not a note.
- **Smalltalk and library items pass.**
- **An errored item is a failure**, never a decline.

Every count comes from the run's own summary fields (`scripts/acceptance.py
--summary-out`), computed by `scripts.acceptance.summarise` from the per-item
result fields. Nothing here infers an outcome from a stream: a decline streams
a delta too, and lane B2's probe nearly reported a false failure rate for
exactly that reason.

The set is also pinned by size and class mix (`EXPECTED_COUNTS`), so a summary
from a filtered run (`acceptance.py id1,id2`) cannot pass as a whole-set
verdict. That is the whole reason `--summary-out` writes the counts rather than
the caller scraping the printed table.

Usage: `python -m evals.acceptance_gate .data/evals/summary-acceptance.json`
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# The whole set, by class. Read here rather than counted from the summary so a
# set that grew or shrank cannot pass against a stale bar: a run that graded
# 11 of 12 is not 12/12, and a summary over 4 filtered items is not this gate.
#
# The mix moved from 33/20 to 32/21 on 2026-10-12 (phase 1c item 2):
# `amb-bovary-homais` was relabelled `answer` → `not_in_sources` because the
# eye-consultation scene its label depends on is not in this edition of
# Madame Bovary at all (`Rouard` is 0 hits corpus-wide). Labels only; the
# reasoning and the measurement are in `evals/acceptance/books.json` and
# `docs/reviews/2026-10-12-2031-ki70-signals.md`.
EXPECTED_COUNTS = {
    "items": 57,
    "answer_items": 32,
    "abstain_items": 21,
    "smalltalk_items": 2,
    "library_items": 2,
}

# PRD §5, as the brief takes it for one run. Named with the arithmetic rather
# than as bare numbers so a reader can see which clause each is. The percentages
# are integers and the arithmetic is integer arithmetic, because
# `math.ceil(20 * 0.90)` is 19 — 0.9 is not exact in binary and the gate must
# not quietly tighten itself by one item. The counts in the comments are the
# ones these rates produce at the CURRENT mix: 19 of 21, and 1 of 32.
MIN_CLEAN_DECLINE_PERCENT = 90  # ≥ 90% of should-decline items → 19 of 21
MAX_FALSE_ABSTENTION_PERCENT = 5  # ≤ 5% of answerable items → 1 of 32
MAX_CONFIDENT_WRONG = 0  # PRD §5 allows ≤1 per 100; on 21 items, 0
# KI-71 (owner decision 2026-10-12): answering a content question from model
# memory is the one thing this product says it does not do, so an `answer`
# item that completed with no citation is a failure at any text quality. Not a
# rate: one is one.
MAX_UNCITED_ANSWERS = 0


def min_clean_declines(abstain_items: int) -> int:
    """The smallest clean-decline count that meets the rate, rounded up."""
    return -(-abstain_items * MIN_CLEAN_DECLINE_PERCENT // 100)


def max_false_abstentions(answer_items: int) -> int:
    """The largest false-abstention count the rate allows, rounded down."""
    return answer_items * MAX_FALSE_ABSTENTION_PERCENT // 100


def _count(summary: Mapping[str, Any], key: str) -> int:
    """One count out of `summary["counts"]`, 0 when the run did not report it.

    A missing count reads as 0 rather than raising, so a truncated summary is
    classified as *not passing* by the other rules instead of crashing — and the
    `items` check below is what actually catches it.
    """
    counts = summary.get("counts")
    if not isinstance(counts, Mapping):
        return 0
    value = counts.get(key)
    return int(value) if isinstance(value, int | float) else 0


def _ids(summary: Mapping[str, Any], key: str) -> list[str]:
    detail = summary.get("detail")
    if not isinstance(detail, Mapping):
        return []
    value = detail.get(key)
    return [str(item) for item in value] if isinstance(value, list) else []


def acceptance_failures(summary: Mapping[str, Any]) -> list[str]:
    """Why this run does not meet PRD §5 on the books set. Empty means it does.

    Each failure carries the number that decided it, so the check reports a
    count rather than a verdict.
    """
    failures: list[str] = []

    # An errored item is not a decline and not a pass. It produced no behaviour
    # to grade, and counting it as either would turn a provider error into a
    # result. Checked first, because it is the one failure that can hide the
    # rest: an error inside the abstain class lowers every rate below.
    errored = _count(summary, "errored")
    if errored:
        failures.append(
            f"{errored} item(s) errored: {_ids(summary, 'errored_ids')}; an errored "
            "item is a failure, never a decline"
        )

    # The whole set, by class. A summary from a filtered run, or a set that
    # changed, is not a verdict on this gate.
    for key, expected in EXPECTED_COUNTS.items():
        got = _count(summary, key)
        if got != expected:
            failures.append(
                f"the run graded {got} {key}, not {expected}: the set changed or the "
                "run was filtered, so this is not a whole-set measurement"
            )
    if failures:
        # The class mix is wrong; the rates below would be computed over the
        # wrong denominators and read as a verdict on something else.
        return failures

    confident_wrong = _count(summary, "confident_wrong")
    if confident_wrong > MAX_CONFIDENT_WRONG:
        failures.append(
            f"{confident_wrong} confident wrong answer(s): {_ids(summary, 'confident_wrong_ids')}"
            " — a reply to a should-abstain item that asserts an answer (PRD §5)"
        )

    abstain_items = _count(summary, "abstain_items")
    clean = _count(summary, "clean_declines")
    min_clean = min_clean_declines(abstain_items)
    if clean < min_clean:
        failures.append(
            f"{clean} of {abstain_items} clean declines ({_count(summary, 'unclean_declines')} "
            f"unclean, {confident_wrong} answered instead of declining); PRD §5 wants "
            f"≥ {MIN_CLEAN_DECLINE_PERCENT}% → at least {min_clean}"
        )

    answer_items = _count(summary, "answer_items")
    false_abstentions = _count(summary, "false_abstentions")
    max_false = max_false_abstentions(answer_items)
    if false_abstentions > max_false:
        failures.append(
            f"{false_abstentions} of {answer_items} answerable items declined "
            f"({_ids(summary, 'false_abstention_ids')}); PRD §5 allows ≤ "
            f"{MAX_FALSE_ABSTENTION_PERCENT}% → at most {max_false}"
        )

    # Checked after the rates because it is a *different* axis: a run can hold
    # every number above and still fail here. `broad-sherlock`'s run passed
    # decline accuracy and false abstention and was still an answer from model
    # memory with nothing behind it (KI-71).
    uncited = _count(summary, "uncited_answers")
    if uncited > MAX_UNCITED_ANSWERS:
        failures.append(
            f"{uncited} answer-class item(s) completed with zero citations: "
            f"{_ids(summary, 'uncited_answer_ids')} — an answer with no evidence "
            "behind it. The text may be right; the reply is still ungrounded, and "
            "answering a content question from memory is the one thing this "
            "product does not do (KI-71)"
        )

    # The two small classes are pass/fail in full: they exist to catch a
    # regression in chitchat handling and in the library answer, where a rate
    # over two items means nothing.
    for key, label in (("smalltalk_items", "smalltalk"), ("library_items", "library")):
        total = _count(summary, key)
        failed = [id_ for id_ in _ids(summary, "failed_ids") if _is_class(summary, id_, label)]
        if len(failed) == total:
            failures.append(f"all {total} {label} items failed: {failed}")
        elif failed:
            failures.append(f"{len(failed)} of {total} {label} items failed: {failed}")

    return failures


def _is_class(summary: Mapping[str, Any], item_id: str, expect: str) -> bool:
    """Whether `item_id` is an item of class `expect`, from the summary's items."""
    items = summary.get("items")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, Mapping) and item.get("id") == item_id and item.get("expect") == expect
        for item in items
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m evals.acceptance_gate <summary.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        # No file is not a pass: the run either never happened or never wrote
        # its summary, and either way nothing was measured.
        print(f"ACCEPTANCE FAIL: no summary at {path}; nothing was measured", file=sys.stderr)
        return 1
    summary = json.loads(path.read_text())
    served = summary.get("served_commit", "unknown")
    failures = acceptance_failures(summary)
    if failures:
        print("ACCEPTANCE FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    counts = summary.get("counts", {})
    print(
        "ACCEPTANCE PASS (PRD §5, one run): "
        f"{counts.get('clean_declines')}/{counts.get('abstain_items')} clean declines, "
        f"{counts.get('confident_wrong')} confident wrong, "
        f"{counts.get('false_abstentions')}/{counts.get('answer_items')} false abstentions, "
        f"{counts.get('uncited_answers', 0)} uncited answers, "
        "smalltalk and library pass, 0 errored"
    )
    print(f"  api served commit: {served}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))