"""Verdict for the entity_mismatch set (phase 1, `make check-work` step 5).

Every item in `evals/entity_mismatch/items.json` asks about an entity that is
attested only in a corpus that is deliberately out of scope, so the correct
answer to all 12 is a decline, and anything else is the KI-54 failure: the run
asserting the in-scope manual's answer to a question the sources cannot answer.

The verdict is computed from the run summary's own fields, never inferred from
the stream. A decline streams a delta too, so a probe that counts "did the
answer stream anything" reports every decline as an answer and manufactures a
failure rate out of correct behaviour (lane B2). The three numbers that decide
it are `failed`, `clean_declines` and `confident_wrong_answers`, and
`evals.runner.aggregate` computes all three from `EvalResult.abstained`,
`EvalResult.error` and `evals.abstention.is_confident_wrong`.

Usage: `python -m evals.entity_gate .data/evals/entity_mismatch.json`
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path

# The whole set. Read here rather than counted from a file so a set that grew
# or shrank cannot quietly pass against a stale expectation: a run that graded
# 11 of 12 is not 12/12 clean declines, and saying so is the point of this.
EXPECTED_ITEMS = 12


def _count(summary: Mapping[str, float | None], key: str) -> float:
    value = summary.get(key)
    return 0.0 if value is None else float(value)


def entity_mismatch_failures(
    summary: Mapping[str, float | None], *, expected_items: int = EXPECTED_ITEMS
) -> list[str]:
    """Why this run is not 12/12 clean declines. Empty list means it is.

    Each failure carries the number that decided it, so the check reports a
    count rather than a verdict.
    """
    failures: list[str] = []

    # An errored item is not a decline. It produced no behaviour to grade, and
    # counting it as a decline would turn a provider error into a pass.
    failed = _count(summary, "failed")
    if failed:
        failures.append(
            f"{failed:.0f} of {expected_items} items errored; an errored item is "
            "not a decline (see the per-item detail above for the error)"
        )

    items = _count(summary, "items")
    if items != expected_items:
        failures.append(
            f"the run graded {items:.0f} items, not {expected_items}: the set "
            "changed or items were dropped, so 12/12 is not a measurement"
        )

    clean = _count(summary, "clean_declines")
    if clean != expected_items:
        failures.append(
            f"{clean:.0f} of {expected_items} clean declines "
            f"({_count(summary, 'unclean_declines'):.0f} unclean, i.e. declined "
            "in prose rather than abstained)"
        )

    confident_wrong = _count(summary, "confident_wrong_answers")
    if confident_wrong:
        failures.append(
            f"{confident_wrong:.0f} confident wrong answers (PRD §5): a reply to "
            "a should-abstain item that asserts an answer"
        )

    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m evals.entity_gate <summary.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        # No file is not a pass: the run either never happened or never wrote
        # its summary, and either way nothing was measured.
        print(f"ENTITY-MISMATCH FAIL: no summary at {path}; nothing was measured", file=sys.stderr)
        return 1
    summary = json.loads(path.read_text())
    failures = entity_mismatch_failures(summary)
    if failures:
        print("ENTITY-MISMATCH FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"ENTITY-MISMATCH PASS: {EXPECTED_ITEMS}/{EXPECTED_ITEMS} clean declines, "
        "0 confident wrong, 0 errored"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))