"""Run the reviewer over the seeded negatives in the judge-validation sheet.

P1b Phase 2 item 0: the seeded rows (real claims rewritten to be unsupported
or contradicted) get the reviewer's verdict, recorded in the hidden
`_reviewer_*` columns. The count of caught negatives (reviewer says
unsupported/contradicted) is the strictness number for item 5. The seeded
rows occupy one real Jev round-trip per batch; 15 rows ≈ $0.01.

    uv run python scripts/review_seeded_claims.py --sheet ../../evals/judge_validation/claims.csv
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decisions.engine import DecisionEngine
from graph.review import ExtractedClaim, verify_claims
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk

DEFAULT_SHEET = Path(__file__).resolve().parents[3] / "evals" / "judge_validation" / "claims.csv"


async def run(sheet: Path) -> None:
    rows = list(csv.DictReader(sheet.open(newline="", encoding="utf-8")))
    seeded = [r for r in rows if r.get("_seeded")]
    if not seeded:
        raise SystemExit("no seeded rows in the sheet")
    engine = DecisionEngine()
    claims = [
        ExtractedClaim(r["claim_id"], r["claim"], [1], True) for r in seeded
    ]
    contexts = [
        ExpandedContext(
            chunk=ScoredChunk(
                chunk_id=uuid4(),
                document_id=None,
                document_name=None,
                section_id=None,
                ord=0,
                page=None,
                text=r["cited_passage"],
                heading_path=None,
                source_type="seed",
                vector_score=None,
                bm25_score=None,
                fused_score=0.0,
            ),
            context_text=r["cited_passage"],
        )
        for r in seeded
    ]
    # verify_claims batches by claim; each here has exactly one cited context,
    # so a context per claim means one call each is unnecessary — batch all by
    # giving every claim the shared list is wrong; instead run one at a time.
    for r, claim, ctx in zip(seeded, claims, contexts, strict=True):
        verified, _ = await verify_claims(
            engine, run_id="seeded-negatives",
            claims=[claim], contexts=[ctx], citation_count=1,
        )
        v = verified[0]
        r["_reviewer_verdict"] = v.verdict
        r["_reviewer_p_supported"] = str(v.p_supported)
        r["_reviewer_engine"] = v.engine
        print(
            f"{r['_seeded']:>12} -> reviewer: {v.verdict} "
            f"(p={v.p_supported}, {v.engine}) :: {r['claim'][:60]}"
        )
    fields = list(rows[0].keys())
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    caught = sum(1 for r in seeded if r["_reviewer_verdict"] in ("unsupported", "contradicted"))
    print(f"\nstrictness: reviewer caught {caught}/{len(seeded)} seeded negatives")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = ap.parse_args()
    asyncio.run(run(args.sheet))


if __name__ == "__main__":
    main()
