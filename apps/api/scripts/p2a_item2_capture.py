"""P2a item 2 capture (KI-52): run the committed claim-extraction prompt over
the four seeded compound claims (the P1b misses) and check the outputs into
tests/fixtures/p2a_item2_captures.json for the tests.

The four rows are claims_proxy.csv rows 23/27/35/40
(20261003-seeded:c5/c3/c8/c2): each welds a true fact to an invented
addition, and v2 must split the addition out as its own claim.

    uv run python scripts/p2a_item2_capture.py
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: F401  # env loading side effect, like other scripts
from evals.runner import SMALL_MODEL
from graph.review import extract_claims

DEFAULT_SHEET = (
    Path(__file__).resolve().parents[3] / "evals" / "judge_validation" / "claims.csv"
)
OUT_FILE = Path(__file__).resolve().parents[3] / "apps" / "api" / "tests" / "fixtures" / (
    "p2a_item2_captures.json"
)
# claims_proxy.csv rows 23/27/35/40 — the four seeded misses (KI-52).
SEED_IDS = [
    "20261003-seeded:c5",
    "20261003-seeded:c3",
    "20261003-seeded:c8",
    "20261003-seeded:c2",
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = ap.parse_args()

    rows = {
        r["claim_id"]: r
        for r in csv.DictReader(args.sheet.open(newline="", encoding="utf-8"))
        if r.get("_seeded")
    }
    missing = [s for s in SEED_IDS if s not in rows]
    if missing:
        raise SystemExit(f"seeded rows missing from the sheet: {missing}")

    out: dict[str, dict[str, object]] = {}
    for seed_id in SEED_IDS:
        row = rows[seed_id]
        claims = await extract_claims(answer=row["claim"], small_model=SMALL_MODEL)
        out[seed_id] = {
            "compound_claim": row["claim"],
            "extracted": [
                {"claim": c.text, "citation_ids": c.citation_ids, "is_factual": c.is_factual}
                for c in claims
            ],
        }
        print(f"{seed_id}: {len(claims)} claim(s)")
        for c in claims:
            print(f"   - {c.text}")
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"captured {len(out)} rows to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
