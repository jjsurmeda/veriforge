# ruff: noqa: E501, E731, B023, S324, ASYNC240, F841
"""Paired Jev vs LLM-judge latency, cost and agreement per decision area ($0 replay).

Reads what `shadow_api.py` (call log), `shadow_resolve.py` (generation records),
`shadow_dump.sh` (database dumps) and `shadow_gold.py` (gold chunks, passage
digests) wrote. No network, no database.

    python -m scripts.shadow_analyze --dir ../../.data/shadow [--out report.md]

Unit of latency and cost is one `decide()` batch (a call), never a decision
key: every key of a batch repeats the batch's latency, so counting keys would
weight a 78-passage rerank 78 times.
"""

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

LEVEL = {
    "off-topic": 0.0,
    "related but does not answer the question": 1 / 3,
    "partly answers the question": 2 / 3,
    "fully answers the question": 1.0,
}
# decision area (key prefix) -> (kind, threshold, label). Shipped values
# (decisions/thresholds.py, the owner's list); Choice kinds are exact-label.
AREA = {
    "passage": ("rerank", 0.455, "floor 0.455 on the passage score"),
    "entity": ("noul", 0.5, "entity 0.5"),
    "conflict": ("noul", 0.6, "conflict 0.60"),
    "is_use": ("noul", 0.47, "is_use 0.47"),
    "prose_decline": ("noul", 0.7, "prose_decline 0.70"),
    "chunk_injection": ("noul", 0.85, "injection 0.85"),
    "guard_injection": ("noul", 0.85, "injection 0.85"),
    "guard_jailbreak": ("noul", 0.85, "jailbreak 0.85"),
    "guard_pii": ("noul", 0.7, "pii 0.70"),
    "off_topic": ("noul", 0.8, "off_topic 0.80"),
    "output_toxicity": ("noul", 0.85, "toxicity 0.85"),
    "output_secrets": ("noul", 0.6, "secrets 0.60"),
    "lexical_weight": ("score", None, "no threshold"),
    "intent": ("choice", None, "exact label"),
    "complexity": ("choice", None, "exact label"),
    "source": ("choice", None, "exact label"),
    "risk": ("choice", None, "exact label"),
    "c": ("choice", None, "exact label (claim verdict)"),
}


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))]


def area_of(key: str) -> str:
    return key.rstrip("0123456789_") or key


def rerank_score(answer: dict[str, Any]) -> float:
    probs = answer.get("probs") or {}
    total = sum(probs.values())
    if probs and total > 0:
        return min(max(sum(LEVEL.get(k, 0.0) * v for k, v in probs.items()) / total, 0.0), 1.0)
    return LEVEL.get(str(answer.get("value")), 0.0)


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def fmt(v: float | None, nd: int = 0) -> str:
    return "n/a" if v is None else f"{v:,.{nd}f}"


def load(d: Path) -> dict[str, Any]:
    calls = [json.loads(line) for line in (d / "calls.jsonl").read_text().splitlines()]
    gens = json.loads((d / "calls.gens.json").read_text())
    return {"calls": calls, "gens": gens}


def attach_costs(calls: list[dict[str, Any]], gens: dict[str, Any]) -> None:
    """Sum generation records per call: USD, native tokens in/out, ids."""
    by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in calls:
        if r["type"] == "gen" and r.get("id") and r.get("call"):
            by_call[r["call"]].append(r)
    for r in calls:
        if r["type"] != "call":
            continue
        usd = tin = tout = 0.0
        missing = 0
        for g in by_call.get(r["call"], []):
            rec = gens.get(g["id"], {})
            if not rec or "unresolved" in rec:
                missing += 1
                continue
            usd += rec.get("total_cost") or 0.0
            tin += rec.get("native_tokens_prompt") or rec.get("tokens_prompt") or 0
            tout += rec.get("native_tokens_completion") or rec.get("tokens_completion") or 0
        r["usd"], r["tin"], r["tout"] = usd, tin, tout
        r["n_gen"], r["gen_missing"] = len(by_call.get(r["call"], [])), missing


def stage_table(calls: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    cs = [r for r in calls if r["type"] == "call" and r["engine"] == "jev"]
    js = [r for r in calls if r["type"] == "call" and r["engine"] == "judge" and r["shadow"]]
    by_pair = {r["pair"]: r for r in js if r["pair"]}
    stages = sorted({r["stage"] or "?" for r in cs + js})
    out: dict[str, Any] = {}
    lines = [
        "| stage (areas) | Jev calls | judge calls ok/err | Jev p50 / p95 ms | judge p50 / p95 ms "
        "| speed x (p50) | paired x (median) | decisions per call | Jev $/1k dec | judge $/1k dec "
        "| cost x | Jev tok in/out per call | judge tok in/out per call | judge $/call | Jev $/call |",
        "|" + "---|" * 15,
    ]
    for st in stages:
        jc = [r for r in cs if (r["stage"] or "?") == st]
        sc = [r for r in js if (r["stage"] or "?") == st]
        ok = [r for r in sc if "error" not in r]
        jok = [r for r in jc if "error" not in r]
        areas = sorted({a for r in jc + sc for a in r["areas"]})
        jl = [r["wall_ms"] for r in jok]
        sl = [r["wall_ms"] for r in ok]
        paired = [
            by_pair[r["call"]]["wall_ms"] / r["wall_ms"]
            for r in jok
            if r["call"] in by_pair and "error" not in by_pair[r["call"]] and r["wall_ms"]
        ]
        dec_j = sum(r["batch"] for r in jc)
        dec_s = sum(r["batch"] for r in sc)
        cj = sum(r.get("usd", 0.0) for r in jc)
        cs_ = sum(r.get("usd", 0.0) for r in sc)
        per_j = cj / dec_j * 1000 if dec_j else None
        per_s = cs_ / dec_s * 1000 if dec_s else None
        ratio_t = (pct(sl, 0.5) / pct(jl, 0.5)) if jl and sl else None
        ratio_c = (per_s / per_j) if per_j and per_s else None
        row = {
            "jev_n": len(jc),
            "judge_ok": len(ok),
            "judge_err": len(sc) - len(ok),
            "jev_p50": pct(jl, 0.5),
            "jev_p95": pct(jl, 0.95),
            "judge_p50": pct(sl, 0.5),
            "judge_p95": pct(sl, 0.95),
            "speed_x": ratio_t,
            "paired_x": statistics.median(paired) if paired else None,
            "paired_n": len(paired),
            "per_call_batch": statistics.fmean([r["batch"] for r in jc]) if jc else None,
            "jev_usd_1k": per_j,
            "judge_usd_1k": per_s,
            "cost_x": ratio_c,
            "jev_tin": statistics.fmean([r["tin"] for r in jc]) if jc else None,
            "jev_tout": statistics.fmean([r["tout"] for r in jc]) if jc else None,
            "judge_tin": statistics.fmean([r["tin"] for r in sc]) if sc else None,
            "judge_tout": statistics.fmean([r["tout"] for r in sc]) if sc else None,
            "jev_usd_call": cj / len(jc) if jc else None,
            "judge_usd_call": cs_ / len(sc) if sc else None,
            "areas": areas,
        }
        out[st] = row
        lines.append(
            f"| {st} ({', '.join(areas)}) | {len(jc)} | {len(ok)}/{len(sc) - len(ok)} "
            f"| {fmt(row['jev_p50'])} / {fmt(row['jev_p95'])} | {fmt(row['judge_p50'])} / {fmt(row['judge_p95'])} "
            f"| {fmt(ratio_t, 1)} | {fmt(row['paired_x'], 1)} (n={len(paired)}) | {fmt(row['per_call_batch'], 1)} "
            f"| {fmt(per_j, 3)} | {fmt(per_s, 3)} | {fmt(ratio_c, 1)} "
            f"| {fmt(row['jev_tin'])}/{fmt(row['jev_tout'])} | {fmt(row['judge_tin'])}/{fmt(row['judge_tout'])} "
            f"| {fmt(row['judge_usd_call'] and row['judge_usd_call'] * 1000, 3)}m | {fmt(row['jev_usd_call'] and row['jev_usd_call'] * 1000, 3)}m |"
        )
    return lines, out


def agreement(calls: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    jev = {
        r["call"]: r
        for r in calls
        if r["type"] == "call" and r["engine"] == "jev" and "error" not in r
    }
    pairs = [
        (jev[r["pair"]], r)
        for r in calls
        if r["type"] == "call"
        and r["engine"] == "judge"
        and r["shadow"]
        and "error" not in r
        and r["pair"] in jev
    ]
    per: dict[str, list[tuple[dict[str, Any], dict[str, Any], str]]] = defaultdict(list)
    for jv, jd in pairs:
        for k, a in jv["answers"].items():
            b = jd["answers"].get(k)
            if b is not None:
                per[area_of(k)].append((a, b, jv["call"]))
    lines = [
        "| area | kind, rule | n pairs | agree | agree % | Jev hi / judge lo | Jev lo / judge hi | mean abs diff | Spearman |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    out: dict[str, Any] = {}
    for area in sorted(per):
        kind, thr, label = AREA.get(area, ("noul", 0.5, "default 0.5"))
        rows = per[area]
        if kind == "choice":
            agree = sum(str(a["value"]) == str(b["value"]) for a, b, _ in rows)
            hi = lo = None
            diffs = [0.0 if str(a["value"]) == str(b["value"]) else 1.0 for a, b, _ in rows]
            rho = None
        else:
            if kind == "rerank":
                xs = [rerank_score(a) for a, _, _ in rows]
                ys = [rerank_score(b) for _, b, _ in rows]
            else:
                xs = [float(a["value"]) for a, _, _ in rows]
                ys = [float(b["value"]) for _, b, _ in rows]
            if thr is None:
                agree = sum(abs(x - y) <= 0.2 for x, y in zip(xs, ys, strict=True))
                hi = lo = None
                label = "no threshold; |diff| <= 0.20"
            else:
                agree = sum((x >= thr) == (y >= thr) for x, y in zip(xs, ys, strict=True))
                hi = sum(x >= thr and y < thr for x, y in zip(xs, ys, strict=True))
                lo = sum(x < thr and y >= thr for x, y in zip(xs, ys, strict=True))
            diffs = [abs(x - y) for x, y in zip(xs, ys, strict=True)]
            rho = spearman(xs, ys)
        n = len(rows)
        out[area] = {
            "n": n,
            "agree": agree,
            "hi": hi,
            "lo": lo,
            "mad": statistics.fmean(diffs),
            "rho": rho,
        }
        lines.append(
            f"| {area} | {kind}, {label} | {n} | {agree} | {agree / n * 100:.0f}% | {fmt(hi)} | {fmt(lo)} "
            f"| {statistics.fmean(diffs):.3f} | {fmt(rho, 2)} |"
        )
    return lines, out


def rerank_section(
    calls: list[dict[str, Any]], d: Path, books: dict[str, Any]
) -> tuple[list[str], dict[str, Any]]:
    gold = json.loads((d / "dump/gold.json").read_text())
    cmap = json.loads((d / "dump/chunkmap.json").read_text())["digest"]
    messages = json.loads((d / "dump/messages.json").read_text())
    runs = json.loads((d / "dump/runs.json").read_text())
    # run -> item id: the last user message of its chat matched to the item's last turn
    turn_to_item = {
        i["turns"][-1] if isinstance(i["turns"][-1], str) else i["turns"][-1].get("text", ""): i[
            "id"
        ]
        for i in books["items"]
    }
    chat_of_run = {m["run_id"]: m["chat_id"] for m in messages}
    item_of_run: dict[str, str] = {}
    for run_id, chat in chat_of_run.items():
        users = [m for m in messages if m["chat_id"] == chat and m["role"] == "user"]
        for m in users:
            item = turn_to_item.get(m["content"])
            if item:
                item_of_run[run_id] = item
    jev = {
        r["call"]: r
        for r in calls
        if r["type"] == "call"
        and r["engine"] == "jev"
        and r["stage"] == "rerank"
        and "error" not in r
    }
    pairs = [
        (jev[r["pair"]], r)
        for r in calls
        if r["type"] == "call"
        and r["engine"] == "judge"
        and r["shadow"]
        and r["stage"] == "rerank"
        and "error" not in r
        and r["pair"] in jev
    ]
    overlaps: list[int] = []
    rhos: list[float] = []
    hits: dict[str, dict[str, bool]] = {"jev": {}, "judge": {}}
    pool_has: dict[str, bool] = {}
    floor_agree = stream_agree = n_pool = 0
    unmapped = total_p = 0
    for jv, jd in pairs:

        def scores(rec: dict[str, Any]) -> dict[int, float]:
            return {int(k.split("_")[1]): rerank_score(a) for k, a in rec["answers"].items()}

        sj, sd = scores(jv), scores(jd)
        idx = sorted(sj)
        rank = lambda s: sorted(idx, key=lambda i: -s.get(i, 0.0))  # stable: ties keep pool order
        top_j, top_d = rank(sj)[:8], rank(sd)[:8]
        overlaps.append(len(set(top_j) & set(top_d)))
        r = spearman([sj[i] for i in idx], [sd.get(i, 0.0) for i in idx])
        if r is not None:
            rhos.append(r)
        m3j = statistics.fmean(sorted(sj.values(), reverse=True)[:3])
        m3d = statistics.fmean(sorted(sd.values(), reverse=True)[:3])
        floor_agree += (m3j >= 0.455) == (m3d >= 0.455)
        stream_agree += (m3j >= 0.60) == (m3d >= 0.60)
        n_pool += 1
        item = item_of_run.get(jv["run_id"])
        if not item or item not in gold or not gold[item]:
            continue
        g = set(gold[item])

        def chunk(i: int) -> set[str]:
            nonlocal unmapped, total_p
            total_p += 1
            ids = set(cmap.get(jv["pdig"].get(f"passage_{i}", ""), []))
            if not ids:
                unmapped += 1
            return ids

        for name, top in (("jev", top_j), ("judge", top_d)):
            hit = any(chunk(i) & g for i in top)
            hits[name][item] = hits[name].get(item, False) or hit
        pool_has[item] = pool_has.get(item, False) or any(chunk(i) & g for i in idx)
    common = sorted(set(hits["jev"]) & set(hits["judge"]))
    lines = [
        f"- paired rerank pools (both engines answered): {n_pool}; top-8 overlap by pool index: "
        f"mean {fmt(statistics.fmean(overlaps) if overlaps else None, 2)} of 8 (min {min(overlaps) if overlaps else 'n/a'}); "
        f"per-pool Spearman mean {fmt(statistics.fmean(rhos) if rhos else None, 2)} (n={len(rhos)})",
        f"- item floor (mean of top-3 score >= 0.455) agreement: {floor_agree}/{n_pool}; stream line (>= 0.60): {stream_agree}/{n_pool}",
        f"- labelled answerable items with a paired rerank: {len(common)}; gold in the pool for {sum(pool_has.get(i, False) for i in common)} of them",
        f"- recall@8 (any gold chunk in the top 8 of any of the item's pools): Jev {sum(hits['jev'][i] for i in common)}/{len(common)}, "
        f"judge {sum(hits['judge'][i] for i in common)}/{len(common)}",
        f"- passage digests with no chunk match: {unmapped}/{total_p}",
        "- items where they differ: "
        + ", ".join(
            f"{i} (Jev {int(hits['jev'][i])}, judge {int(hits['judge'][i])})"
            for i in common
            if hits["jev"][i] != hits["judge"][i]
        ),
    ]
    return lines, {"overlaps": overlaps, "common": common, "hits": hits}


def totals(calls: list[dict[str, Any]], gens: dict[str, Any]) -> list[str]:
    """Spend by bucket over the whole run set. Roles that carry no run id in
    their litellm metadata (rewriter, titler, claim_extractor, suggester,
    async_judge) are summed as a role bucket and spread evenly over the runs."""
    bucket: dict[str, float] = defaultdict(float)
    runs: set[str] = set()
    for r in calls:
        if r["type"] == "call":
            runs.add(r["run_id"] or "")
        if r["type"] != "gen" or not r.get("id"):
            continue
        usd = (gens.get(r["id"]) or {}).get("total_cost") or 0.0
        role = r.get("role") or "?"
        if r["source"] == "jev":
            role = "jev_decisions"
        elif role == "decision_fallback":
            role = "judge_decisions"
        bucket[role] += usd
    runs.discard("")
    n = len(runs)
    rows = [f"| {k} | {v:.4f} | {v / n:.5f} |" for k, v in sorted(bucket.items())]
    base = sum(v for k, v in bucket.items() if k not in ("jev_decisions", "judge_decisions", "async_judge"))
    jev, judge = bucket["jev_decisions"], bucket["judge_decisions"]
    return [
        f"{n} runs with decision calls; total attributed to roles ${sum(bucket.values()):.4f}",
        "",
        "| cost bucket | total $ | $ per run |",
        "|---|---|---|",
        *rows,
        "",
        f"- decision layer per run: Jev ${jev / n:.5f}; judge on the same inputs ${judge / n:.5f} "
        f"({judge / jev:.1f}x)",
        f"- whole run, Jev primary (generator + rewriter/claim_extractor/suggester/titler + Jev decisions; "
        f"excludes the shadow judge and async_judge): ${(base + jev) / n:.5f}",
        f"- whole run, judge as the decision engine on the same inputs (flow held fixed, so a lower "
        f"bound: the fallback_only runs took extra evidence cycles): ${(base + judge) / n:.5f}",
        f"- async_judge (background, both cases): ${bucket['async_judge'] / n:.5f} per run",
    ]


def inflight(calls: list[dict[str, Any]]) -> list[str]:
    """Judge latency without our own queueing: the time inside litellm.acompletion
    (after the per-model slot is taken), summed over the call's attempts."""
    gen_ms: dict[str, int] = defaultdict(int)
    for r in calls:
        if r["type"] == "gen" and r["source"] == "litellm" and r.get("call"):
            gen_ms[r["call"]] += r.get("open_ms") or 0
    js = [r for r in calls if r["type"] == "call" and r["engine"] == "judge" and r["shadow"] and "error" not in r]
    lines = [
        "| stage | n | judge wall p50 / p95 ms | judge in-flight p50 / p95 ms (no slot wait) | queued share of wall (median) | Jev p50 ms | in-flight x Jev (p50) |",
        "|---|---|---|---|---|---|---|",
    ]
    for st in sorted({r["stage"] for r in js}):
        rs = [r for r in js if r["stage"] == st]
        jev_p50 = pct([r["wall_ms"] for r in calls if r["type"] == "call" and r["engine"] == "jev" and r["stage"] == st and "error" not in r], .5)
        wall = [r["wall_ms"] for r in rs]
        fly = [gen_ms[r["call"]] for r in rs]
        share = [1 - gen_ms[r["call"]] / r["wall_ms"] for r in rs if r["wall_ms"]]
        lines.append(
            f"| {st} | {len(rs)} | {fmt(pct(wall, .5))} / {fmt(pct(wall, .95))} | "
            f"{fmt(pct(fly, .5))} / {fmt(pct(fly, .95))} | {statistics.median(share) * 100:.0f}% | "
            f"{fmt(jev_p50)} | {fmt(pct(fly, .5) / jev_p50, 1)} |"
        )
    return lines


def errors(calls: list[dict[str, Any]]) -> list[str]:
    tally: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in calls:
        if r["type"] == "call" and r.get("error"):
            tally[(r["engine"], r["stage"], r["error"][:110])] += 1
    out = [f"- {n} x {e} / {st}: {msg}" for (e, st, msg), n in sorted(tally.items())]
    ue = [r["err"] for r in calls if r["type"] == "usage_error"]
    out.append(f"- shadow `record_call` errors swallowed by the launcher: {len(ue)} ({', '.join(sorted(set(ue)))})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument(
        "--books",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "evals/acceptance/books.json",
    )
    args = ap.parse_args()
    data = load(args.dir)
    attach_costs(data["calls"], data["gens"])
    books = json.loads(args.books.read_text())
    t1, s1 = stage_table(data["calls"])
    t2, s2 = agreement(data["calls"])
    print("## Per stage (one row per decision batch type)\n")
    print("\n".join(t1))
    print("\n## Agreement per decision area (paired, same input)\n")
    print("\n".join(t2))
    if (args.dir / "dump/gold.json").exists() and (args.dir / "dump/messages.json").exists():
        t3, _ = rerank_section(data["calls"], args.dir, books)
        print("\n## Rerank\n")
        print("\n".join(t3))
    print("\n## Judge latency with and without our own queueing\n")
    print("\n".join(inflight(data["calls"])))
    print("\n## Failed calls\n")
    print("\n".join(errors(data["calls"])))
    print("\n## Totals\n")
    print("\n".join(totals(data["calls"], data["gens"])))
    (args.dir / "analysis.json").write_text(
        json.dumps({"stages": s1, "agreement": s2}, indent=1, default=str)
    )


if __name__ == "__main__":
    sys.exit(main())
