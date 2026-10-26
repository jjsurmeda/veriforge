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
- **False abstention ≤ 5%** of answerable items — 1 of 32.
- **An `answer`-class item that completed with zero citations fails**, whether
  its text was right or wrong. This is KI-71: ingress can classify a content
  question as `chitchat`, the run skips retrieval and answers from model
  memory, and every other clause above passes — a correct, warm, uncited
  reply is the failure shape this product exists not to ship. Answering a
  content question from memory is the one thing the product says it doesn't
  do, so the bar is a count like the others, not a note.
- **≤ 1 content miss of the answerable items.** An `answer`-class item that
  answered, cited, and still did not state the strings the item requires. The
  plan's bar names it, and nothing else here can see it: such an item is not a
  decline, not an abstention, not an error, not uncited, and it cited the right
  book.
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

Usage: `python -m evals.acceptance_gate .data/evals/summary-acceptance.json [--set=deep]`

R2b item 2 adds the **deep** set: the 14-item Deep replay over the books
corpus (evals/deep/items.json — 10 multi-hop answerables, 4
should-declines). Its bar is its own, not PRD §5's books table: **0
confident wrong**, **≤ 1 content miss**, **an errored item fails**, the
**pinned counts** below, and **p50 item wall clock ≤ 45 s** (ADR-003, 2026-10-25). Clean/unclean
declines, false abstentions and uncited answers are reported by the
summary and the runner but not gated: R2b is the first Deep measurement
under the new floor + guard + IsUse tail, and the report is what the
numbers are for.
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
# Madame Bovary at all (`Rouard` is 0 hits corpus-wide). It moved back to
# 33/20 on 2026-10-17 (ADR-006): `ml-zh-xiyou-nezha` was relabelled
# `not_in_sources` → `answer` — the corpus does state that the Heavenly
# King lives in the Cloud Tower Palace (雲樓宮) and calls Nezha there.
# It moved to 32/20 (57 → 56 items) on 2026-10-22 (KI-80): `outside-whitman`
# was removed. The only passage says Whitman draws "a fine and just
# distinction" but never says what it is, so the question is not answerable
# from the corpus and every generator abstained on it. Removed after the
# R3 generator runs had seen it: reported with both the 57- and 56-item results.
# Labels only; the
# reasoning and the measurement are in `evals/acceptance/books.json` and
EXPECTED_COUNTS = {
    "items": 56,
    "answer_items": 32,
    "abstain_items": 20,
    "smalltalk_items": 2,
    "library_items": 2,
}

# The held-out set (evals/heldout/items.json, plan bar 2026-10-17): 31 items over
# books the pipeline was never tuned on. Its bar is the plan's: 0 confident wrong
# and at most 5% false abstention overall, reported per category. It has no
# smalltalk or library class, so it cannot be judged against the books mix.
HELDOUT_COUNTS = {
    "items": 31,
    "answer_items": 21,
    "abstain_items": 10,
    "smalltalk_items": 0,
    "library_items": 0,
}
# The Deep set (R2b item 2, evals/deep/items.json): 14 items replayed in Deep
# mode over the books corpus — 10 multi-hop answerables and 4 should-declines
# that look in-corpus. Its bar is the plan's Deep bar, not the books one: the
# evidence floor and the entity guard (R2b item 1) make Deep declines a
# different mechanism from Auto's, so this set is scored as a whole-set
# verdict on its own terms, and turn-latency is part of the bar.
DEEP_COUNTS = {
    "items": 14,
    "answer_items": 10,
    "abstain_items": 4,
    "smalltalk_items": 0,
    "library_items": 0,
}
# R2b's bar: a multi-hop run that meets every accuracy clause but takes three
# minutes is not shippable as Deep. p50 of the per-item wall clock
# (`p50_total_ms`, measured POST → run.completed) at most 45 s (ADR-003 entry,
# 2026-10-25: was 30 s, set before Deep was measured).
MAX_P50_TOTAL_MS = 45_000
# The two frozen Deep splits (evals/deep/test_items.json over the books corpus,
# evals/deep/heldout_items.json over the held-out corpus): same Deep bar as
# "deep", their own pinned sizes. Registration only; no clause changed.
DEEP_TEST_COUNTS = {**DEEP_COUNTS, "items": 16, "answer_items": 10, "abstain_items": 6}
DEEP_HELDOUT_COUNTS = {**DEEP_COUNTS, "items": 8, "answer_items": 4, "abstain_items": 4}
# The unseen Deep set (evals/deep/unseen_items.json, books corpus, frozen
# 2026-10-26, written before any run): 14 answerable, 6 should-decline.
DEEP_UNSEEN_COUNTS = {**DEEP_COUNTS, "items": 20, "answer_items": 14, "abstain_items": 6}
DEEP_SETS = ("deep", "deep_test", "deep_heldout", "deep_unseen")
EXPECTED_BY_SET = {
    "books": EXPECTED_COUNTS,
    "heldout": HELDOUT_COUNTS,
    "deep": DEEP_COUNTS,
    "deep_test": DEEP_TEST_COUNTS,
    "deep_heldout": DEEP_HELDOUT_COUNTS,
    "deep_unseen": DEEP_UNSEEN_COUNTS,
}

# PRD §5, as the brief takes it for one run. Named with the arithmetic rather
# than as bare numbers so a reader can see which clause each is. The arithmetic
# is integer ceiling division (-(-21 * 90 // 100) = 19), never `math.ceil` over
# binary floats: 0.9 is inexact and the gate must not quietly tighten itself by
# one item. The counts in the comments are the ones these rates produce at the
# CURRENT mix: 18 of 20, and 1 of 32.
MIN_CLEAN_DECLINE_PERCENT = 90  # ≥ 90% of should-decline items → 18 of 20
MAX_FALSE_ABSTENTION_PERCENT = 5  # ≤ 5% of answerable items → 1 of 32
MAX_CONFIDENT_WRONG = 0  # PRD §5 allows ≤1 per 100; on 20 items, 0
# KI-71 (owner decision 2026-10-12): answering a content question from model
# memory is the one thing this product says it does not do, so an `answer`
# item that completed with no citation is a failure at any text quality. Not a
# rate: one is one.
MAX_UNCITED_ANSWERS = 0
# KI-75 / the plan's bar line: "≤ 1 content miss of 32 answerables". A content
# miss is an answer-class item that answered, cited, and still did not state the
# strings the item requires. Every other clause above passes such an item — it
# is not a decline, not an abstention, not an error, not uncited, and the book
# it cited is the right one — so without this clause a run that is confidently
# wrong about the thing it was asked passes the whole gate. PRD §5's 1 is the
# bar, and it is the same arithmetic as `MAX_FALSE_ABSTENTION_PERCENT` at this
# mix (32 * 5% = 1.6, floored to 1).
MAX_CONTENT_MISSES = 1


HELDOUT_ITEMS = Path(__file__).resolve().parents[3] / "evals" / "heldout" / "items.json"


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


def acceptance_failures(summary: Mapping[str, Any], set_name: str = "books") -> list[str]:
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
    for key, expected in EXPECTED_BY_SET[set_name].items():
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
    # The plan's held-out bar names confident wrong and false abstention only;
    # clean declines are reported for it, not gated (no clause added
    # mid-phase). The Deep set's declines are a different mechanism (the
    # R2b evidence floor, not Auto's prose rules), measured here by the
    # other clauses plus latency.
    if set_name == "books" and clean < min_clean:
        failures.append(
            f"{clean} of {abstain_items} clean declines ({_count(summary, 'unclean_declines')} "
            f"unclean, {confident_wrong} answered instead of declining); PRD §5 wants "
            f"≥ {MIN_CLEAN_DECLINE_PERCENT}% → at least {min_clean}"
        )

    answer_items = _count(summary, "answer_items")
    false_abstentions = _count(summary, "false_abstentions")
    max_false = max_false_abstentions(answer_items)
    if set_name not in DEEP_SETS and false_abstentions > max_false:
        failures.append(
            f"{false_abstentions} of {answer_items} answerable items declined "
            f"({_ids(summary, 'false_abstention_ids')}); PRD §5 allows ≤ "
            f"{MAX_FALSE_ABSTENTION_PERCENT}% → at most {max_false}"
        )

    # Checked after the rates because it is a *different* axis: a run can hold
    # every number above and still fail here. `broad-sherlock`'s run passed
    # decline accuracy and false abstention and was still an answer from model
    # memory with nothing behind it.
    uncited = _count(summary, "uncited_answers")
    if set_name not in DEEP_SETS and uncited > MAX_UNCITED_ANSWERS:
        failures.append(
            f"{uncited} answer-class item(s) completed with zero citations: "
            f"{_ids(summary, 'uncited_answer_ids')} — an answer with no evidence "
            "behind it. The text may be right; the reply is still ungrounded, and "
            "answering a content question from memory is the one thing this "
            "product does not do"
        )

    # Content correctness, checked last because it is the clause a run can pass
    # everything else on. A cited answer that does not state the required
    # mention is not a decline, an abstention, an error or an uncited answer;
    # before KI-75 it was visible only as a name in `failed_ids`, which nothing
    # counted.
    content_misses = _count(summary, "content_misses")
    if content_misses > MAX_CONTENT_MISSES:
        failures.append(
            f"{content_misses} of {answer_items} answerable items answered but did not "
            f"state the required content: {_ids(summary, 'content_miss_ids')}; the bar "
            f"allows ≤ {MAX_CONTENT_MISSES} content miss"
        )

    # R2b item 2: Deep's own latency clause. `p50_total_ms` is the median of the
    # per-item wall clock (POST → run.completed) the runner records; absent
    # (-1) or late both fail, because "slow but correct" is not Deep shipping.
    if set_name in DEEP_SETS:
        p50 = summary.get("p50_total_ms")
        if not isinstance(p50, int | float) or p50 < 0:
            failures.append(
                "no p50_total_ms in the summary (or no item measured one); the "
                "Deep bar reads a latency median from a --summary-out run"
            )
        elif p50 > MAX_P50_TOTAL_MS:
            failures.append(
                f"p50 item wall clock {int(p50)} ms > {MAX_P50_TOTAL_MS} ms; a "
                "multi-hop answer arriving three minutes late is not shippable "
                "as Deep"
            )  # The two small classes are pass/fail in full: they exist to catch a
    # regression in chitchat handling and in the library answer, where a rate
    # over two items means nothing.
    for key, label in (("smalltalk_items", "smalltalk"), ("library_items", "library")):
        total = _count(summary, key)
        failed = [id_ for id_ in _ids(summary, "failed_ids") if _is_class(summary, id_, label)]
        if not total:
            continue  # a set with no items of this class (the held-out set)
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


def category_report(summary: Mapping[str, Any], categories: Mapping[str, str]) -> list[str]:
    """Per-category pass counts from the summary's own rows ('reported per
    category', plan bar). `categories` maps item id to category."""
    items = summary.get("items")
    if not isinstance(items, list):
        return []
    tally: dict[str, list[int]] = {}
    for row in items:
        if isinstance(row, Mapping):
            cell = tally.setdefault(categories.get(str(row.get("id")), "uncategorised"), [0, 0])
            cell[1] += 1
            cell[0] += int(bool(row.get("pass")))
    return [f"  {name}: {ok}/{n}" for name, (ok, n) in sorted(tally.items())]


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--set=")]
    set_name = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--set=")), "books")
    if len(args) != 1 or set_name not in EXPECTED_BY_SET:
        print(
            "usage: python -m evals.acceptance_gate <summary.json> "
            "[--set=books|heldout|deep|deep_test|deep_heldout|deep_unseen]",
            file=sys.stderr,
        )
        return 2
    path = Path(args[0])
    if not path.exists():
        # No file is not a pass: the run either never happened or never wrote
        # its summary, and either way nothing was measured.
        print(f"ACCEPTANCE FAIL: no summary at {path}; nothing was measured", file=sys.stderr)
        return 1
    summary = json.loads(path.read_text())
    served = summary.get("served_commit", "unknown")
    failures = acceptance_failures(summary, set_name)
    if set_name == "heldout":
        heldout = json.loads(HELDOUT_ITEMS.read_text())["items"]
        print("per category (pass/items):")
        for line in category_report(summary, {i["id"]: i["category"] for i in heldout}):
            print(line)
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
        f"{counts.get('content_misses', 0)} content misses, "
        "smalltalk and library pass, 0 errored"
    )
    print(f"  api served commit: {served}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
