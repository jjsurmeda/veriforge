"""Replay NVIDIA and Jev reranking on identical fused candidates (C2 item 4).

Offline by construction: candidates are captured once, then both rerankers
are handed the same list and no generation happens. That isolates the
reranker — the only thing that differs between the two arms.

    python scripts/compare_rerankers.py [--limit N] [--out PATH]

Per item it records where the expected book first appears in the reranked
order, whether a `mention` term survives into the top 8, and the rerank
latency. For the Jev arm it also reads OpenRouter's generation stats for
the per-call cost and notes whether the call fell back to the LLM, so the
report can quote $/query rather than call counts.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import get_settings
from db.models import Collection
from decisions.engine import DecisionEngine
from decisions.jev import JevClient
from evals.attribution import _stats
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import ScoredChunk, hybrid_search
from retrieval.rerank import JevRerank, NvidiaRerank
from runtime import (
    RuntimeSettings,
    reset_runtime_settings,
    set_runtime_settings,
)

SET_FILE = Path(__file__).resolve().parents[3] / "evals/acceptance/books.json"
OUT_DEFAULT = Path(".data/rerank-comparison.json")
TOP_N = 8
FUSED_LIMIT = 40
LEXICAL_WEIGHT = 0.5


@dataclass
class ItemResult:
    item_id: str
    reranker: str
    candidates: int
    first_rank_of_expected: int | None
    mention_in_top8: bool | None
    latency_ms: int
    fell_back: bool
    cost_usd: float | None


def _expected_names(item: dict[str, Any]) -> list[str]:
    return [str(c) for c in item.get("cite", [])]


def _rank_of_expected(chunks: list[ScoredChunk], expected: list[str]) -> int | None:
    for position, chunk in enumerate(chunks, start=1):
        name = (chunk.document_name or "").lower()
        if any(book.lower() in name for book in expected):
            return position
    return None


def _mention_in_top8(chunks: list[ScoredChunk], mention: list[str]) -> bool | None:
    if not mention:
        return None
    top = " ".join(c.text.lower() for c in chunks[:TOP_N])
    return any(m.lower() in top for m in mention)


async def _shared_scope(session: Any) -> tuple[Any, list[Any]]:
    """Every shared collection, plus an owner id build_scope will accept.

    A comparison needs no per-user isolation — the same candidate list goes to
    both arms — but build_scope insists on a real owner, so use the account
    that publishes the Shared library. All shared collections are in scope,
    not just one: that is what resolve_scope gives a real run.
    """
    rows = (
        await session.execute(
            select(Collection.id, Collection.owner_id)
            .where(Collection.visibility == "shared")
            .order_by(Collection.created_at)
        )
    ).all()
    if not rows:
        raise SystemExit("no shared collection; run `make seed-books` first")
    return rows[0].owner_id, [row.id for row in rows]


async def _capture_candidates(
    session: Any, question: str, owner_id: Any, collection_ids: list[Any]
) -> list[ScoredChunk]:
    """The fused top 40 exactly as retrieval produces them, minus rerank."""
    from retrieval.cache import get_query_embedding

    embedding = await get_query_embedding(session, question)
    fused = await hybrid_search(
        session,
        query_text=question,
        query_embedding=embedding,
        ownership=Ownership(user_id=owner_id, collection_ids=collection_ids),
        filters=ClientFilters(),
        lexical_weight=LEXICAL_WEIGHT,
    )
    return fused[:FUSED_LIMIT]


# Every Jev call in this run appends its generation id here; each item's cost
# is whatever landed during its own call.
GENERATION_IDS: list[str] = []


async def _usd_for(ids: list[str]) -> float | None:
    """Real USD from OpenRouter's generation record, not the credit estimate.

    The store is written asynchronously, so a lookup straight after the call
    404s for a while; `evals.attribution._stats` already retries that.
    """
    total = 0.0
    seen = False
    for generation_id in ids:
        data, _status, _attempts = await _stats(generation_id)
        if data is None:
            continue
        seen = True
        total += float(data.get("total_cost") or 0.0)
    return total if seen else None


def _cost_recording_client(ids: list[str]) -> httpx.AsyncClient:
    async def on_response(response: httpx.Response) -> None:
        generation_id = response.headers.get("x-generation-id")
        if generation_id:
            ids.append(generation_id)

    return httpx.AsyncClient(event_hooks={"response": [on_response]})


async def _run_one(
    name: str,
    reranker: Any,
    candidates: list[ScoredChunk],
    item: dict[str, Any],
) -> ItemResult:
    from decisions.breaker import BreakerState, get_breaker

    documents = [c.text for c in candidates]
    opened_before = get_breaker().state is BreakerState.OPEN
    already = len(GENERATION_IDS)
    started = time.perf_counter()
    ranked = await reranker.rerank(query=item["turns"][-1], documents=documents, top_n=TOP_N)
    latency_ms = int((time.perf_counter() - started) * 1000)
    fresh = GENERATION_IDS[already:]
    cost_usd = await _usd_for(fresh) if name == "jev" and fresh else 0.0
    # A breaker that opens during the call means Jev was unreachable and the
    # LLM fallback answered, so this row is not a Jev measurement.
    fell_back = (
        name == "jev" and not opened_before and get_breaker().state is BreakerState.OPEN
    )
    ordered = [candidates[i] for i, _ in ranked]
    return ItemResult(
        item_id=str(item["id"]),
        reranker=name,
        candidates=len(candidates),
        first_rank_of_expected=_rank_of_expected(ordered, _expected_names(item)),
        mention_in_top8=_mention_in_top8(ordered, [str(m) for m in item.get("mention", [])]),
        latency_ms=latency_ms,
        fell_back=fell_back,
        cost_usd=cost_usd,
    )


def _report(rows: list[ItemResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in sorted({r.reranker for r in rows}):
        arm = [r for r in rows if r.reranker == name]
        ranks = [r.first_rank_of_expected for r in arm if r.first_rank_of_expected is not None]
        mentions = [r.mention_in_top8 for r in arm if r.mention_in_top8 is not None]
        costs = [r.cost_usd for r in arm if r.cost_usd is not None]
        out[name] = {
            "items": len(arm),
            "recall_at_8": round(len(ranks) / len(arm), 3) if arm else 0.0,
            "mean_rank_of_expected": round(statistics.mean(ranks), 2) if ranks else None,
            "mention_recall_at_8": round(sum(1 for m in mentions if m) / len(mentions), 3)
            if mentions
            else None,
            "p50_latency_ms": int(statistics.median([r.latency_ms for r in arm])) if arm else 0,
            "usd_per_query": round(statistics.mean(costs), 6) if costs else None,
            "fell_back": sum(1 for r in arm if r.fell_back),
        }
    return out


async def main(limit: int | None, out_path: Path) -> None:
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("NVIDIA_API_KEY is not set; cannot replay the nvidia arm")
    dataset = json.loads(SET_FILE.read_text())
    items = [i for i in dataset["items"] if i["expect"] == "answer"]
    if limit is not None:
        items = items[:limit]

    engine = DecisionEngine(
        jev=JevClient(client=_cost_recording_client(GENERATION_IDS)), mode="auto"
    )
    nvidia = NvidiaRerank(settings.nvidia_api_key, settings.nvidia_rerank_model)
    rows: list[ItemResult] = []
    async with _uncached_session() as session:
        owner_id, collection_ids = await _shared_scope(session)
        for item in items:
            candidates = await _capture_candidates(
                session, str(item["turns"][-1]), owner_id, collection_ids
            )
            if not candidates:
                print(f"  {item['id']}: no fused candidates, skipped", flush=True)
                continue
            rows.append(await _run_one("nvidia", nvidia, candidates, item))
            token = set_runtime_settings(_jev_runtime())
            try:
                rows.append(
                    await _run_one(
                        "jev",
                        JevRerank(engine, str(item["id"])),
                        candidates,
                        item,
                    )
                )
            finally:
                reset_runtime_settings(token)
            last = rows[-2:]
            print(
                f"  {item['id']}: "
                + "  ".join(
                    f"{r.reranker} rank={r.first_rank_of_expected} "
                    f"mention={r.mention_in_top8} {r.latency_ms}ms"
                    for r in last
                ),
                flush=True,
            )

    report = _report(rows)
    await asyncio.to_thread(
        out_path.parent.mkdir, parents=True, exist_ok=True
    )
    await asyncio.to_thread(
        out_path.write_text,
        json.dumps({"rows": [asdict(r) for r in rows], "report": report}, indent=1),
    )
    print("\n| reranker | recall@8 | mean rank | mention@8 | p50 ms | $/query | fell back |")
    print("|---|---|---|---|---|---|---|")
    for name, stats in report.items():
        print(
            f"| {name} | {stats['recall_at_8']} | {stats['mean_rank_of_expected']} "
            f"| {stats['mention_recall_at_8']} | {stats['p50_latency_ms']} "
            f"| {stats['usd_per_query']} | {stats['fell_back']} |"
        )
    print(f"\nraw: {out_path}")


@asynccontextmanager
async def _uncached_session() -> Any:
    """A session whose connection has no prepared-statement cache.

    pg_search's custom bm25 scan node cannot be re-planned out of asyncpg's
    statement cache ("unrecognized node type"). `statement_cache_size=0` is
    the documented way out; `DEALLOCATE ALL` is not, because it also throws
    away asyncpg's own cached statements. Scoped to this script — a one-off
    comparison is not the place to change the app's pool settings.
    """
    engine = create_async_engine(
        get_settings().database_url, connect_args={"statement_cache_size": 0}
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


def _jev_runtime() -> RuntimeSettings:
    return RuntimeSettings.from_data(1, {"retrieval": {"reranker": "jev"}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.out))
