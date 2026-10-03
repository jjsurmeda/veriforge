"""P2a item 1 measurement (KI-53): re-score the 30 recorded proxy-labelled
answers through the new reviewer (extraction + absence-claim verification,
no revision pass), and compare reviewer faithfulness against the proxy
"grounded" label.

The recorded answers are `evals/judge_validation/answers.csv` (P1b's
acceptance/export runs, passages included); the proxy labels are
`.data/judge_proxy/answers_proxy.csv` (Opus-blind — proxy, NOT human).
Neither file is written to; results go to `.data/evals/p2a-item1-measure.json`.

The 15 export rows (data rows 16-30) are the scored set of P2a item 1; the
15 acceptance rows (1-15) are reported alongside. Agreement on a row:
`(faithfulness >= 0.90) == (proxy_grounded == "yes")`. P1b's baseline:
7/15 on the export rows (the reviewer rated every recorded answer 1.0).

    uv run python scripts/p2a_item1_measure.py
"""

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: F401  # env loading side effect, like other scripts
from decisions import DecisionEngine
from graph.review import extract_claims, score_review, verify_claims
from providers.llm import complete  # noqa: F401  # default complete_fn
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk

DEFAULT_ANSWERS = (
    Path(__file__).resolve().parents[3] / "evals" / "judge_validation" / "answers.csv"
)
DEFAULT_PROXY = (
    Path(__file__).resolve().parents[3] / ".data" / "judge_proxy" / "answers_proxy.csv"
)
OUT_FILE = Path(__file__).resolve().parents[3] / ".data" / "evals" / "p2a-item1-measure.json"
SMALL_MODEL = "openrouter/openai/gpt-4o-mini"

_SPLIT = "\n---\n"
_LEAD = re.compile(r"^\[\d+\]\s*")
FLOOR = 0.90


def parse_passages(field: str) -> list[str]:
    out = []
    for part in field.strip().split(_SPLIT):
        part = part.strip()
        if part:
            out.append(_LEAD.sub("", part, count=1))
    return out


def _contexts(passages: list[str]) -> list[ExpandedContext]:
    return [
        ExpandedContext(
            chunk=ScoredChunk(
                chunk_id=uuid4(),
                document_id=None,
                document_name=None,
                section_id=None,
                ord=0,
                page=None,
                text=p,
                heading_path=None,
                source_type="document",
                vector_score=None,
                bm25_score=None,
                fused_score=0.0,
            ),
            context_text=p,
        )
        for p in passages
    ]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    ap.add_argument("--proxy", type=Path, default=DEFAULT_PROXY)
    args = ap.parse_args()

    rows = list(csv.DictReader(args.answers.open(newline="", encoding="utf-8")))
    proxy = {
        r["answer_id"]: r["proxy_grounded"].strip().lower()
        for r in csv.DictReader(args.proxy.open(newline="", encoding="utf-8"))
    }

    engine = DecisionEngine()
    results = []
    for i, row in enumerate(rows, start=1):
        answer_id = row["answer_id"]
        contexts = _contexts(parse_passages(row["passages"]))
        claims = await extract_claims(answer=row["answer"], small_model=SMALL_MODEL)
        verified, _ = await verify_claims(
            engine,
            run_id=f"p2a-item1-{i:02d}",
            claims=claims,
            contexts=contexts,
            citation_count=len(contexts),
        )
        scores = score_review(verified, citation_count=len(contexts))
        grounded_proxy = proxy.get(answer_id, "?")
        faithful = scores.faithfulness >= FLOOR
        agree = faithful == (grounded_proxy == "yes")
        results.append(
            {
                "row": i,
                "answer_id": answer_id,
                "export_row": i >= 16,
                "proxy_grounded": grounded_proxy,
                "faithfulness": scores.faithfulness,
                "min_support": scores.min_support,
                "faithfulness_ge_0_90": faithful,
                "agrees_with_proxy": agree,
                "claims": [
                    {
                        "id": v.claim.claim_id,
                        "text": v.claim.text,
                        "citation_ids": v.claim.citation_ids,
                        "verdict": v.verdict,
                        "p_supported": v.p_supported,
                    }
                    for v in verified
                ],
            }
        )
        print(
            f"row {i:2d} {answer_id:<38} proxy={grounded_proxy:<3} "
            f"faith={scores.faithfulness:.2f} agree={agree}"
        )

    export = [r for r in results if r["export_row"]]
    export_agree = sum(1 for r in export if r["agrees_with_proxy"])
    all_agree = sum(1 for r in results if r["agrees_with_proxy"])
    summary = {
        "note": "proxy labels: .data/judge_proxy/answers_proxy.csv (Opus-blind, proxy not human)",
        "faithfulness_floor": FLOOR,
        "export_rows_total": len(export),
        "export_rows_agree": export_agree,
        "all_rows_total": len(results),
        "all_rows_agree": all_agree,
        "rows": results,
    }
    OUT_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"\nagreement on the 15 export (scored) rows: {export_agree}/{len(export)} "
        f"(P1b baseline 7/15; target >= 13/15)"
    )
    print(f"agreement on all 30 rows: {all_agree}/{len(results)}")
    print(f"saved to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
