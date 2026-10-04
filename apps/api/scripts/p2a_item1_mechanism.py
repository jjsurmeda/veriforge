"""P2a item 1 mechanism proof (KI-53): v3 vs candidate v4 on the proxy-labelled
false-absence and 5 GHz rows.

Takes the 8 rows the proxy flagged (six false absence sentences + the two
5 GHz over-inferences), feeds each its exact recorded passages through the
generator exactly as `graph/generate.py` builds the messages, once with the
current `grounded_answer.md` v3 and once with the candidate v4, and prints
both answers. ~16 gpt-4o-mini calls, a few cents.

    uv run python scripts/p2a_item1_mechanism.py
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
from graph.generate import build_grounded_messages
from providers.llm import complete
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk

DEFAULT_ANSWERS = (
    Path(__file__).resolve().parents[3] / "evals" / "judge_validation" / "answers.csv"
)
DEFAULT_CANDIDATE = (
    Path(__file__).resolve().parents[3] / ".data" / "evals" / "p2a_item1_v4_candidate.md"
)
OUT_FILE = Path(__file__).resolve().parents[3] / ".data" / "evals" / "p2a-item1-mechanism.json"
GENERATOR_MODEL = "openrouter/openai/gpt-4o-mini"

# proxy row 13/16/17/20/25/26: false absence sentence; 27/29: 5 GHz
# over-inference. Keyed by answers.csv row order (1-based data rows).
FLAGGED_ROWS = [13, 16, 17, 20, 25, 26, 27, 29]

_SPLIT_RE = re.compile(r"\n---\n")
_LEAD_RE = re.compile(r"^\[\d+\]\s*")


def parse_passages(field: str) -> list[str]:
    passages: list[str] = []
    for part in _SPLIT_RE.split(field.strip()):
        part = part.strip()
        if part:
            passages.append(_LEAD_RE.sub("", part, count=1))
    return passages


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


async def _generate(system: str, question: str, contexts: list[ExpandedContext]) -> str:
    messages = [
        {"role": "system", "content": system},
    ]
    for user in build_grounded_messages(question, contexts, [])[1:]:
        messages.append(user)
    response = await complete(
        litellm_model=GENERATOR_MODEL,
        messages=messages,
        metadata={"job": "p2a_item1_mechanism", "role": "generator"},
    )
    return str(response).strip()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    ap.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    ap.add_argument("--rows", type=str, default=",".join(str(n) for n in FLAGGED_ROWS))
    args = ap.parse_args()

    from prompts.load import load_prompt

    v3 = load_prompt("grounded_answer.md")
    v4 = args.candidate.read_text(encoding="utf-8")
    if v4.startswith("---"):
        v4 = v4.split("---", 2)[2].strip()

    rows = list(csv.DictReader(args.answers.open(newline="", encoding="utf-8")))
    picks = [int(n) for n in args.rows.split(",") if n.strip()]
    out: dict[str, dict[str, object]] = {}
    for n in picks:
        row = rows[n - 1]
        answer_id = row["answer_id"]
        question = row["question"]
        contexts = _contexts(parse_passages(row["passages"]))
        print(f"=== row {n} :: {answer_id} :: {question}\n")
        a3 = await _generate(v3, question, contexts)
        a4 = await _generate(v4, question, contexts)
        out[answer_id] = {
            "row": n,
            "question": question,
            "v3_answer": a3,
            "v4_answer": a4,
        }
        print(f"--- v3 ---\n{a3}\n")
        print(f"--- candidate v4 ---\n{a4}\n")
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"captured {len(out)} rows to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
