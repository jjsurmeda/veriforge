"""Retrieval recall@pool for the books acceptance set (rag-reference Evaluation).

Replays the retrieval queries an acceptance run recorded (its raw results file)
against the acceptance database and reports, for each BM25 reserve size,
whether each answerable item's labelled answer passage
(`evals/acceptance/answer_passages.json`) reaches the pool. Gist items are
scored on whether any passage of their document does. The weight is the one
ingress recorded for that query (`run_events`), so the reserve is the only
thing that changes. The only provider call is the query embeddings.

    DATABASE_URL=...accept_db uv run python -m scripts.measure_recall \\
        ../../.data/acceptance/<run>.json --reserves 0,8
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from db.session import get_session_factory
from providers.llm import embed_batch
from retrieval import hybrid
from retrieval.filters import Ownership

LABELS = Path(__file__).resolve().parents[3] / "evals" / "acceptance" / "answer_passages.json"


async def _gold(session: Any, label: dict[str, Any]) -> set[str]:
    doc = f"%{label['doc']}%"
    if label.get("gist"):
        rows = await session.execute(
            text(
                "select c.id from chunks c join documents d on d.id = c.document_id "
                "where d.name ilike :doc"
            ),
            {"doc": doc},
        )
        return {str(r[0]) for r in rows}
    found: set[str] = set()
    for quote in label["quotes"]:
        rows = await session.execute(
            text(
                "select c.id from chunks c join documents d on d.id = c.document_id "
                "where d.name ilike :doc "
                "and regexp_replace(c.text, '\\s+', ' ', 'g') ilike :q"
            ),
            {"doc": doc, "q": f"%{quote}%"},
        )
        found |= {str(r[0]) for r in rows}
    return found


async def _search(factory: Any, **kwargs: Any) -> list[hybrid.ScoredChunk]:
    # ParadeDB intermittently raises "unrecognized node type" when one
    # connection runs the same statement many times in a row (seen only under
    # this replay's tight loop, never in a product run); retry it.
    for attempt in range(5):
        try:
            async with factory() as session:
                return await hybrid.hybrid_search(session, **kwargs)
        except DBAPIError:
            if attempt == 4:
                raise
    raise AssertionError("unreachable")


async def measure(export: Path, reserves: list[int]) -> list[dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = json.loads(await asyncio.to_thread(LABELS.read_text))[
        "items"
    ]
    exported = json.loads(await asyncio.to_thread(export.read_text))
    items = {i["id"]: i for i in exported["items"]}
    factory = get_session_factory()
    async with factory() as session:
        owner = (
            await session.execute(
                text("select owner_id from collections where visibility = 'private' limit 1")
            )
        ).scalar_one()
        collections = [r[0] for r in await session.execute(text("select id from collections"))]
        weights: dict[str, float] = {}
        rows = await session.execute(
            text(
                "select r.payload->>'query', d.payload->>'value' from run_events r "
                "join run_events d on d.run_id = r.run_id and d.type = 'decision' "
                "and d.payload->>'name' = 'lexical_weight' where r.type = 'retrieval'"
            )
        )
        for query, value in rows:
            if query:
                weights.setdefault(query, float(value))
        gold = {iid: await _gold(session, label) for iid, label in labels.items()}
    ownership = Ownership(user_id=UUID(str(owner)), collection_ids=collections)

    out = []
    for iid, label in labels.items():
        queries = list(dict.fromkeys(r["query"] for r in items[iid].get("retrievals") or []))
        row: dict[str, Any] = {"id": iid, "gist": bool(label.get("gist")), "gold": len(gold[iid])}
        if not queries:
            row["note"] = "no retrieval recorded"
            out.append(row)
            continue
        # What the recorded run itself did: the pool it graded, and the
        # passages that came out of the rerank (the ones carrying a grade).
        recorded_pool: set[str] = set()
        recorded_top: set[str] = set()
        for retrieval in items[iid].get("retrievals") or []:
            ids = retrieval.get("chunk_ids") or []
            recorded_pool |= set(ids)
            recorded_top |= {
                cid
                for cid, grade in zip(ids, retrieval.get("rerank_scores") or [], strict=False)
                if grade is not None
            }
        row["recorded"] = {
            "pool": bool(recorded_pool & gold[iid]),
            "after_rerank": bool(recorded_top & gold[iid]),
        }
        embeddings = await embed_batch(texts=queries)
        for n in reserves:
            name = f"reserve{n}"
            hybrid.LEX_RESERVE = n  # read at call time; no runtime settings here
            pool: set[str] = set()
            sizes = []
            for query, embedding in zip(queries, embeddings, strict=True):
                chunks = await _search(
                    factory,
                    query_text=query,
                    query_embedding=embedding,
                    ownership=ownership,
                    lexical_weight=weights.get(query, 0.5),
                )
                ids = {str(c.chunk_id) for c in chunks}
                pool |= ids
                sizes.append(len(ids))
            row[name] = {"hit": bool(pool & gold[iid]), "pool": sum(sizes) / len(sizes)}
        out.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return out


def summarise(rows: list[dict[str, Any]], names: list[str]) -> str:
    # Items with no recorded retrieval count in the denominator as not reached,
    # listed apart so a skipped retrieval cannot inflate the rate.
    lines = []
    for gist in (False, True):
        kind = "gist (document reached)" if gist else "answer-passage hit rate"
        group = [r for r in rows if r["gist"] is gist]
        no_retrieval = [r["id"] for r in group if "note" in r]
        scored = [r for r in group if "recorded" in r]
        for stage in ("pool", "after_rerank"):
            reached = sum(1 for r in scored if r["recorded"][stage])
            lost = [r["id"] for r in scored if not r["recorded"][stage]]
            total = len(scored) + len(no_retrieval)
            lines.append(
                f"recorded run, {stage}: {kind} {reached}/{total}, missed {lost}, "
                f"no_retrieval={no_retrieval}"
            )
    for name in names:
        for gist in (False, True):
            group = [r for r in rows if r["gist"] is gist]
            no_retrieval = [r["id"] for r in group if "note" in r]
            scored = [r for r in group if name in r]
            hits = [r["id"] for r in scored if r[name]["hit"]]
            missed = [r["id"] for r in scored if not r[name]["hit"]]
            pool = sum(r[name]["pool"] for r in scored) / len(scored) if scored else 0
            kind = "gist (document reached)" if gist else "answer-passage hit rate"
            total = len(scored) + len(no_retrieval)
            lines.append(
                f"{name}: {kind} {len(hits)}/{total}, mean pool {pool:.1f}, missed {missed}, "
                f"no_retrieval={no_retrieval}"
            )
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="an acceptance raw results file")
    parser.add_argument("--reserves", default="0,8", help="BM25 reserve sizes to compare")
    parser.add_argument("--out", type=Path, default=None, help="write the rows here as JSON")
    args = parser.parse_args()
    reserves = [int(n) for n in args.reserves.split(",")]
    rows = await measure(args.export, reserves)
    print(summarise(rows, [f"reserve{n}" for n in reserves]))
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
