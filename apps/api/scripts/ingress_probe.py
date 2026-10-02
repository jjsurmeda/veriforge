"""The KI-37 routing probe: call ingress N times on one question and print
the intent distribution (D6 Phase 2).

Read-only: no database writes and no run is started. It builds one
DecisionEngine per call, exactly as `graph/runner.py` does, so the
probabilities are the ones the product would act on.

    docker compose cp apps/api/scripts/ingress_probe.py api:/app/scripts/ingress_probe.py
    docker compose exec -T api /app/.venv/bin/python /app/scripts/ingress_probe.py

KI-37 is the generator answering a containment question with the corpus's
internal filenames, because the run was routed to the `library` shortcut,
which skips retrieval. The probe is how you tell whether that is fixed:
`library` should never be chosen for a containment question, and p(library)
should sit far below `library_min_confidence`.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app")

from decisions.engine import DecisionEngine
from graph.ingress import ingress_questions

QUESTION = "What does the AW-2000 package contain?"
RUNS = 10


async def main() -> None:
    rows: list[dict[str, object]] = []
    for _ in range(RUNS):
        engine = DecisionEngine()
        questions = ingress_questions(QUESTION, has_collections=True)
        answers = await engine.decide(state=QUESTION, questions=questions)
        intent = answers["intent"]
        probabilities = intent.probabilities or {}
        rows.append(
            {
                "intent": str(intent.value),
                "engine": intent.engine,
                "p_library": probabilities.get("library"),
            }
        )
        print(json.dumps(rows[-1]), flush=True)

    library = [r for r in rows if r["intent"] == "library"]
    print("\n=== distribution over", RUNS, "calls ===")
    print("library chosen:", len(library), "of", RUNS)
    values = [r["p_library"] for r in rows if isinstance(r["p_library"], (int, float))]
    if values:
        print("p(library): min", min(values), "max", max(values))


if __name__ == "__main__":
    asyncio.run(main())