"""Validate the IsUse check against labelled triples (plan bar, 2026-10-17).

`evals/isuse_validation/triples.json` holds (question, answer, sources) triples,
half of them answers and half non-answers: an answer to a different question, an
answer from another book, a hedge, and a claim the sources do not make. This asks
the product's own IsUse question (`graph.stages.usefulness_stage.is_use_question`,
through `DecisionEngine`, so Jev answers) for each and reports

- **non-answers passed**: the bar is at most 5% of the labelled non-answers;
- **answers rejected**: the false-abstention side, reported with the ids.

    set -a; . ../../.env; set +a
    uv run python -m scripts.validate_isuse [--out report.json]

Cost: one Jev call per triple (about 60). The labels are constructed, not
sampled from live traffic: a pass here shows the check separates these shapes,
and the held-out run is what shows it on the product's own answers.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from decisions import threshold
from decisions.engine import DecisionEngine
from graph.stages.usefulness_stage import IS_USE_NAME, KIND, is_use_question

TRIPLES = Path(__file__).resolve().parents[3] / "evals" / "isuse_validation" / "triples.json"
MAX_NON_ANSWERS_PASSED = 0.05
MIN_COVERAGE = 0.95


def score(
    triples: Sequence[Mapping[str, Any]], values: Mapping[str, float | None], floor: float
) -> dict[str, Any]:
    """Pass/fail per triple at `floor`. A triple with no value (the call failed)
    counts as failing the check, the way the product's fail-closed rule does, but
    it is left out of the non-answer pass rate. The bar also needs MIN_COVERAGE of
    the triples measured, so an outage cannot pass by default."""

    def passed(triple: Mapping[str, Any]) -> bool:
        value = values.get(triple["id"])
        return value is not None and value >= floor

    measured = {t["id"] for t in triples if values.get(t["id"]) is not None}
    errors = [t["id"] for t in triples if t["id"] not in measured]
    coverage = len(measured) / len(triples) if triples else 0.0
    non_answers = [t for t in triples if t["label"] == "does_not_answer"]
    answers = [t for t in triples if t["label"] == "answers"]
    measured_non_answers = [t for t in non_answers if t["id"] in measured]
    passed_wrong = [t["id"] for t in non_answers if passed(t)]
    rejected = [t["id"] for t in answers if not passed(t)]
    by_kind: dict[str, dict[str, int]] = {}
    for t in triples:
        kind = by_kind.setdefault(t["kind"], {"n": 0, "passed": 0})
        kind["n"] += 1
        kind["passed"] += int(passed(t))
    rate = len(passed_wrong) / len(measured_non_answers) if measured_non_answers else 0.0
    return {
        "floor": floor,
        "measured": len(measured),
        "coverage": coverage,
        "errors": errors,
        "non_answers": len(non_answers),
        "non_answers_passed": passed_wrong,
        "non_answers_passed_rate": rate,
        "answers": len(answers),
        "answers_rejected": rejected,
        "answers_rejected_rate": len(rejected) / len(answers) if answers else 0.0,
        "by_kind": by_kind,
        "bar_ok": coverage >= MIN_COVERAGE and rate <= MAX_NON_ANSWERS_PASSED,
    }


async def measure(triples: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    engine = DecisionEngine()
    values: dict[str, float | None] = {}
    for triple in triples:
        contexts = [SimpleNamespace(context_text=s) for s in triple["sources"]]
        question = is_use_question(triple["question"], triple["answer"], contexts)  # type: ignore[arg-type]
        try:
            answers = await engine.decide(
                state={"run_id": f"isuse-validation-{triple['id']}", "kind": KIND},
                questions={IS_USE_NAME: question},
            )
            values[triple["id"]] = float(answers[IS_USE_NAME].value)
        except Exception as exc:  # recorded as a failed check, like the product
            print(f"{triple['id']}: {exc!r}")
            values[triple["id"]] = None
    return values


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    triples = json.loads(await asyncio.to_thread(TRIPLES.read_text))
    values = await measure(triples)
    report = score(triples, values, float(threshold("is_use", "jev")))
    report["values"] = values
    print(json.dumps({k: v for k, v in report.items() if k != "values"}, indent=1))
    if args.out:
        await asyncio.to_thread(args.out.write_text, json.dumps(report, indent=1))
    if not report["bar_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
