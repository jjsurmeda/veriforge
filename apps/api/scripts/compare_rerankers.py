"""Compare every registered reranker on identical candidate pools (R2c item 6).

Pools come from replaying the retrieval queries an acceptance export recorded
through `hybrid_search`, the way `scripts/measure_recall.py` does, so every
reranker is handed the same fused top 40. No generation happens: the only
provider calls are the query embeddings and the rerankers under test.

    DATABASE_URL=...accept_db uv run python -m scripts.compare_rerankers \\
        ../../.data/acceptance/<run>.json --ids jev,cohere,nvidia,fused

Per reranker it reports the labelled answer passage's after-rerank recall at 8
(`evals/acceptance/answer_passages.json`; gist items count a hit on any passage
of their document), nDCG@10 over the same labels, rerank latency p50 and p95,
and cost per 1,000 queries (Jev from OpenRouter generation stats, the others
from the registry price table), plus paired per-item wins and losses against
Jev. A difference of fewer than 2 items is labelled a tie. A reranker without
its key is skipped and named. Writes `docs/benchmarks/rerankers.md` and a JSON
artefact; with no keys it runs Jev and fused order and says so.
"""

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from config import get_settings
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from decisions.jev import JevClient
from evals.attribution import _stats
from providers.llm import embed_batch
from retrieval.filters import Ownership
from retrieval.rerank import RERANKERS, RerankProvider
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from scripts.measure_recall import LABELS, _gold, _search

ROOT = Path(__file__).resolve().parents[3]
BENCH_MD = ROOT / "docs" / "benchmarks" / "rerankers.md"
BENCH_JSON = ROOT / "docs" / "benchmarks" / "rerankers.json"
FUSED_LIMIT = 40
RECALL_K = 8
NDCG_K = 10
TIE_ITEMS = 2  # paired differences under this many items are ties

GENERATION_IDS: list[str] = []


def ndcg_at_k(ranked_ids: list[str], gold: set[str], k: int = NDCG_K) -> float:
    """Binary-relevance nDCG@k: a chunk is relevant if it is in `gold`."""
    gains = [1.0 if cid in gold else 0.0 for cid in ranked_ids[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]


def paired(hits: dict[str, dict[str, bool]], base: str, other: str) -> dict[str, Any]:
    """Per-item wins and losses of `other` against `base` on the recall@8 hit."""
    ids = sorted(set(hits[base]) & set(hits[other]))
    wins = [i for i in ids if hits[other][i] and not hits[base][i]]
    losses = [i for i in ids if hits[base][i] and not hits[other][i]]
    verdict = (
        "tie"
        if abs(len(wins) - len(losses)) < TIE_ITEMS
        else ("better" if len(wins) > len(losses) else "worse")
    )
    return {"wins": wins, "losses": losses, "verdict": verdict}


def _head_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            cwd=ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _cost_recording_client() -> httpx.AsyncClient:
    async def on_response(response: httpx.Response) -> None:
        generation_id = response.headers.get("x-generation-id")
        if generation_id:
            GENERATION_IDS.append(generation_id)

    return httpx.AsyncClient(event_hooks={"response": [on_response]})


async def _usd_for(ids: list[str]) -> float | None:
    """Real USD from OpenRouter's generation record (written asynchronously;
    `_stats` retries the 404 window)."""
    total, seen = 0.0, False
    for generation_id in ids:
        data, _status, _attempts = await _stats(generation_id)
        if data is not None:
            seen = True
            total += float(data.get("total_cost") or 0.0)
    return total if seen else None


def _build(rid: str, engine: DecisionEngine, run_id: str) -> RerankProvider | None:
    info = RERANKERS[rid]
    return info.build(get_settings(), engine, run_id)


def _available(rid: str) -> tuple[bool, str]:
    settings = get_settings()
    if rid == "jev":
        return (True, "") if settings.openrouter_api_key else (False, "no OPENROUTER_API_KEY")
    if not RERANKERS[rid].key_present(settings):
        return False, "no API key"
    return True, ""


async def _context(session: Any) -> tuple[Ownership, dict[str, float]]:
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
    return Ownership(user_id=UUID(str(owner)), collection_ids=collections), weights


async def measure(
    export: Path, ids: list[str], limit: int | None, pace: float = 0.0
) -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = json.loads(LABELS.read_text())["items"]
    items = {i["id"]: i for i in json.loads(await asyncio.to_thread(export.read_text))["items"]}
    factory = get_session_factory()
    async with factory() as session:
        ownership, weights = await _context(session)
        gold = {iid: await _gold(session, label) for iid, label in labels.items()}

    engine = DecisionEngine(jev=JevClient(client=_cost_recording_client()), mode="auto")
    hits: dict[str, dict[str, bool]] = {rid: {} for rid in ids}
    ndcgs: dict[str, dict[str, float]] = {rid: {} for rid in ids}
    latencies: dict[str, list[float]] = {rid: [] for rid in ids}
    jev_usd: list[float] = []
    queries_run: dict[str, int] = {rid: 0 for rid in ids}
    degraded: dict[str, int] = {rid: 0 for rid in ids}

    scored = [iid for iid in labels if items.get(iid, {}).get("retrievals")]
    if limit:
        scored = scored[:limit]
    for iid in scored:
        queries = list(dict.fromkeys(r["query"] for r in items[iid]["retrievals"]))
        embeddings = await embed_batch(texts=queries)
        item_hit = {rid: False for rid in ids}
        item_failed: set[str] = set()
        item_ndcg: dict[str, list[float]] = {rid: [] for rid in ids}
        for query, embedding in zip(queries, embeddings, strict=True):
            pool = (
                await _search(
                    factory,
                    query_text=query,
                    query_embedding=embedding,
                    ownership=ownership,
                    lexical_weight=weights.get(query, 0.5),
                )
            )[:FUSED_LIMIT]
            if not pool:
                continue
            documents = [c.text for c in pool]
            for rid in ids:  # the identical pool goes to every reranker
                provider = _build(rid, engine, iid)
                assert provider is not None
                token = set_runtime_settings(RuntimeSettings.from_data(1, {}))
                before = len(GENERATION_IDS)
                started = time.perf_counter()
                try:
                    ranked = await provider.rerank(query=query, documents=documents, top_n=NDCG_K)
                except Exception as exc:
                    print(f"    {rid} failed on {iid}: {exc!r}", flush=True)
                    degraded[rid] += 1
                    item_failed.add(rid)
                    continue
                finally:
                    reset_runtime_settings(token)
                    if pace and rid != "jev":
                        await asyncio.sleep(pace)
                latencies[rid].append((time.perf_counter() - started) * 1000)
                queries_run[rid] += 1
                if rid == "jev" and (usd := await _usd_for(GENERATION_IDS[before:])) is not None:
                    jev_usd.append(usd)
                order = [str(pool[i].chunk_id) for i, _ in ranked]
                item_hit[rid] = item_hit[rid] or bool(set(order[:RECALL_K]) & gold[iid])
                item_ndcg[rid].append(ndcg_at_k(order, gold[iid]))
        # An item where a call failed is not scored for that reranker: a rate
        # limit or outage is not a retrieval miss.
        for rid in ids:
            if rid in item_failed:
                continue
            hits[rid][iid] = item_hit[rid]
            ndcgs[rid][iid] = statistics.fmean(item_ndcg[rid]) if item_ndcg[rid] else 0.0
        print(
            f"  {iid}: "
            + " ".join("FAILED" if r in item_failed else f"{r}={int(item_hit[r])}" for r in ids)
            + "",
            flush=True,
        )

    summary: dict[str, Any] = {}
    for rid in ids:
        n = len(hits[rid])
        info = RERANKERS[rid]
        if rid == "jev":
            per_1k = round(statistics.fmean(jev_usd) * 1000, 4) if jev_usd else None
            cost_src = "OpenRouter generation stats" if jev_usd else "not measured"
        else:
            per_1k = info.cost_per_1k_queries_usd
            cost_src = "price table"
        summary[rid] = {
            "items": n,
            "recall_at_8": round(sum(hits[rid].values()) / n, 3) if n else 0.0,
            "hits": sum(hits[rid].values()),
            "ndcg_at_10": round(statistics.fmean(ndcgs[rid].values()), 4) if n else 0.0,
            "latency_p50_ms": round(percentile(latencies[rid], 0.5)),
            "latency_p95_ms": round(percentile(latencies[rid], 0.95)),
            "cost_per_1k_queries_usd": per_1k,
            "cost_source": cost_src,
            "queries": queries_run[rid],
            "failed_calls": degraded[rid],
        }
    vs_jev = {rid: paired(hits, "jev", rid) for rid in ids if rid != "jev" and "jev" in ids}
    return {"summary": summary, "vs_jev": vs_jev, "hits": hits, "ndcg": ndcgs}


def render_md(result: dict[str, Any], *, skipped: dict[str, str], export: Path) -> str:
    lines = [
        "# Reranker comparison",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC at commit `{_head_sha()}` by "
        "`scripts/compare_rerankers.py`.",
        f"Pools: the recorded retrieval queries of `{export.name}` replayed through "
        f"`hybrid_search` (fused top {FUSED_LIMIT}); every reranker saw the identical pool.",
        "Labels: `evals/acceptance/answer_passages.json` (gist items: any passage of the "
        "document). Differences under "
        f"{TIE_ITEMS} items are ties.",
        "",
    ]
    if skipped:
        lines += ["Skipped: " + "; ".join(f"`{k}` ({v})" for k, v in skipped.items()), ""]
    ran = [k for k in result["summary"]]
    if ran == ["jev", "fused"] or set(ran) <= {"jev", "fused"}:
        lines += ["Only Jev and fused order ran: no Cohere or NVIDIA key was present.", ""]
    lines += [
        "| reranker | recall@8 | nDCG@10 | p50 ms | p95 ms | $ / 1k queries | cost source |",
        "|---|---|---|---|---|---|---|",
    ]
    for rid, s in result["summary"].items():
        cost = "n/a" if s["cost_per_1k_queries_usd"] is None else f"{s['cost_per_1k_queries_usd']}"
        lines.append(
            f"| {rid} | {s['hits']}/{s['items']} ({s['recall_at_8']}) | {s['ndcg_at_10']} "
            f"| {s['latency_p50_ms']} | {s['latency_p95_ms']} | {cost} | {s['cost_source']} |"
        )
    for rid, s in result["summary"].items():
        if s["failed_calls"]:
            lines += [
                "",
                f"`{rid}`: {s['failed_calls']} rerank calls failed; the items they hit are "
                f"not scored for it (scored {s['items']} items).",
            ]
    if result["vs_jev"]:
        lines += [
            "",
            "## Paired against Jev (recall@8 per item)",
            "",
            "| reranker | wins | losses | verdict | losses (items) |",
            "|---|---|---|---|---|",
        ]
        for rid, p in result["vs_jev"].items():
            lines.append(
                f"| {rid} | {len(p['wins'])} | {len(p['losses'])} | {p['verdict']} "
                f"| {', '.join(p['losses']) or '-'} |"
            )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="an acceptance raw results file")
    parser.add_argument("--ids", default=",".join(RERANKERS), help="comma-separated registry ids")
    parser.add_argument("--limit", type=int, default=None, help="first N labelled items")
    parser.add_argument(
        "--pace", type=float, default=0.0, help="seconds to wait after each non-Jev rerank call"
    )
    parser.add_argument("--out-md", type=Path, default=BENCH_MD)
    parser.add_argument("--out-json", type=Path, default=BENCH_JSON)
    args = parser.parse_args()

    wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
    unknown = [i for i in wanted if i not in RERANKERS]
    if unknown:
        raise SystemExit(f"unknown reranker id(s) {unknown}; known: {list(RERANKERS)}")
    skipped: dict[str, str] = {}
    ids: list[str] = []
    for rid in wanted:
        ok, why = _available(rid)
        (ids.append(rid) if ok else skipped.__setitem__(rid, why))
    for rid, why in skipped.items():
        print(f"skipping {rid}: {why}")
    if not ids:
        raise SystemExit("no reranker is available to run")

    result = await measure(args.export, ids, args.limit, args.pace)
    md = render_md(result, skipped=skipped, export=args.export)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(md)
    args.out_json.write_text(json.dumps({**result, "skipped": skipped}, indent=1))
    print(md)
    print(f"wrote {args.out_md} and {args.out_json}")


if __name__ == "__main__":
    asyncio.run(main())
