"""P2a item 2 measurement (KI-52): atomic extraction, strictness on the
15 seeded negatives, no drop on the 30 real claims.

Extends P1b's `scripts/review_seeded_claims.py`:

- seeded rows (15): the compound claim is first run through the committed
  claim-extraction prompt; every extracted claim inherits the row's single
  cited passage (P1b's method) and goes through the normal verdict path.
  A row is CAUGHT when any of its claims lands unsupported or contradicted
  — the P2a shape: a true fact plus an invented addition must not average
  out to `partial`.
- real rows (30): plain `verify_claims` on the recorded claim (as P1b did),
  verdict compared against the proxy verdict.

Proxy labels: `.data/judge_proxy/claims_proxy.csv` (Opus-blind — proxy,
NOT human). Neither input file is written to; results go to
`.data/evals/p2a-item2-measure.json`.

Targets (P1b baselines in parentheses): seeded caught >= 13/15 (11/15);
real agreement >= 24/30 (24/30).

    uv run python scripts/p2a_item2_measure.py
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: F401  # env loading side effect, like other scripts
from decisions import DecisionEngine
from evals.runner import SMALL_MODEL
from graph.review import ExtractedClaim, extract_claims, verify_claims
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk

DEFAULT_SHEET = (
    Path(__file__).resolve().parents[3] / "evals" / "judge_validation" / "claims.csv"
)
DEFAULT_PROXY = (
    Path(__file__).resolve().parents[3] / ".data" / "judge_proxy" / "claims_proxy.csv"
)
OUT_FILE = Path(__file__).resolve().parents[3] / ".data" / "evals" / "p2a-item2-measure.json"
CAUGHT = {"unsupported", "contradicted"}


def _context(text: str) -> list[ExpandedContext]:
    chunk = ScoredChunk(
        chunk_id=uuid4(),
        document_id=None,
        document_name=None,
        section_id=None,
        ord=0,
        page=None,
        text=text,
        heading_path=None,
        source_type="seed",
        vector_score=None,
        bm25_score=None,
        fused_score=0.0,
    )
    return [ExpandedContext(chunk, chunk.text)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    ap.add_argument("--proxy", type=Path, default=DEFAULT_PROXY)
    args = ap.parse_args()

    rows = list(csv.DictReader(args.sheet.open(newline="", encoding="utf-8")))
    proxy = {
        r["claim_id"]: r["proxy_verdict"].strip().lower()
        for r in csv.DictReader(args.proxy.open(newline="", encoding="utf-8"))
    }
    engine = DecisionEngine()

    seeded, real = [], []
    for i, row in enumerate(rows):
        passage = _context(row["cited_passage"])
        if row.get("_seeded"):
            claims = await extract_claims(answer=row["claim"], small_model=SMALL_MODEL)
            # The whole compound claim was cited to this one passage; every
            # split conjunct keeps that citation (P1b's method).
            claims = [
                ExtractedClaim(c.claim_id, c.text, [1], c.is_factual) for c in claims
            ]
            verified, _ = await verify_claims(
                engine,
                run_id=f"p2a-item2-seeded-{i:02d}",
                claims=claims,
                contexts=passage,
                citation_count=1,
            )
            verdicts = [v.verdict for v in verified]
            caught = any(v in CAUGHT for v in verdicts)
            seeded.append(
                {
                    "claim_id": row["claim_id"],
                    "compound_claim": row["claim"],
                    "extracted_claims": [
                        {"claim": v.claim.text, "verdict": v.verdict} for v in verified
                    ],
                    "caught": caught,
                }
            )
            print(
                f"seeded  {row['claim_id']:<22} caught={caught} "
                f"({', '.join(f'{v.claim.claim_id}:{v.verdict}' for v in verified)})"
            )
        else:
            claim = ExtractedClaim(row["claim_id"], row["claim"], [1], True)
            verified, _ = await verify_claims(
                engine,
                run_id=f"p2a-item2-real-{i:02d}",
                claims=[claim],
                contexts=passage,
                citation_count=1,
            )
            verdict = verified[0].verdict
            wants = proxy.get(row["claim_id"], "?")
            real.append(
                {
                    "claim_id": row["claim_id"],
                    "claim": row["claim"],
                    "verdict": verdict,
                    "proxy_verdict": wants,
                    "agrees": verdict == wants,
                }
            )
            print(f"real    {row['claim_id']:<22} {verdict:<13} proxy={wants:<12} agree={verdict == wants}")

    caught_n = sum(1 for r in seeded if r["caught"])
    agree_n = sum(1 for r in real if r["agrees"])
    summary = {
        "note": "proxy labels: .data/judge_proxy/claims_proxy.csv (Opus-blind, proxy not human)",
        "seeded_total": len(seeded),
        "seeded_caught": caught_n,
        "real_total": len(real),
        "real_agree": agree_n,
        "seeded_rows": seeded,
        "real_rows": real,
    }
    OUT_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nseeded caught: {caught_n}/{len(seeded)} (P1b 11/15; target >= 13/15)")
    print(f"real agreement: {agree_n}/{len(real)} (P1b 24/30; target >= 24/30)")
    print(f"saved to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
