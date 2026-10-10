"""Item 0 probe: split the `retrieve` stage into its sub-stages, with a number on each.

D7 and P2a report `retrieve` at 4.0-4.7 s p50, but that is one number for a
stage that does a query-variants LLM call, N embeddings and N hybrid searches.
Until each part has its own figure, any change to it is a guess. This script
measures the parts and prints p50, the worst single run, and each part's share
of the run's total time — the table that then orders the rest of the work.

It is a diagnostic, not part of the app: nothing here is imported at runtime,
and it reads the same SSE stream the browser reads (no monkeypatching of the
hot path). Every stage number comes from a `step.started` / `step.completed`
pair the pipeline published itself, or from the first `answer.delta`, so the
probe measures the product rather than a rewritten copy of it.

Usage (needs the local stack up, the eval account, and real provider keys):

    EVAL_USER_EMAIL=... EVAL_USER_PASSWORD=... \\
      uv run python scripts/probe_retrieve_stages.py --questions 10 --runs 2

Latency is measured alone (docs/conventions/agents.md): run it with nothing
else on the machine, with the laptop awake (`caffeinate -dims`), and note any
sleep in the report. Writes `.data/lane-b/probe-<timestamp>.json` beside the
printed table so the after-state run can be diffed against the before-state one.

Only the labelled steps are attributed; everything else in the run (the
reviewer, the post-delivery work) falls into `unattributed`. The residual
inside `retrieve` — whatever the outer step contains that is not a labelled
sub-step — is reported on its own row rather than folded into the searches,
because that residual IS the thing items 1 and 3 change.
"""

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from scripts import acceptance as acceptance
from scripts import smoke_chat as smoke_chat

SET_FILE = Path(__file__).resolve().parents[3] / "evals" / "acceptance" / "books.json"
OUT_DIR = Path(__file__).resolve().parents[3] / ".data" / "lane-b"

# Sub-steps of `retrieve`, by label prefix. Everything that is not a step of
# the Auto path is left in `unattributed` rather than guessed at.
SEARCH_PREFIX = "retrieve: "
# The row names below are the table's left column; the labels that feed them
# are matched by `stage_for_label`.
OUTER_LABELS = {"ingress+rewrite": "ingress+rewrite", "retrieve": "retrieve"}
PLAIN_LABELS = {
    "rerank": "rerank",
    "sanitize": "sanitize",
    "sufficient": "sufficient",
    "conflict": "conflict",
    "query variants": "query variants",
    "query parts": "query parts",
}
# A label that carries a count in it still names one stage: "embed queries (4)"
# and "embed queries" are the same row, not two.
PREFIX_LABELS = {"embed queries": "embed queries"}


def stage_for_label(label: str) -> str:
    """The table row a step label belongs to.

    Unknown labels keep their own name: a stage the pipeline grew later shows
    up in the table instead of disappearing into a residual.
    """
    if label.startswith(SEARCH_PREFIX):
        return "hybrid searches (all variants)"
    if label in PLAIN_LABELS:
        return PLAIN_LABELS[label]
    for prefix, row in PREFIX_LABELS.items():
        if label.startswith(prefix):
            return row
    return label


@dataclass
class StageStat:
    stage: str
    p50_ms: float
    worst_ms: float
    share: float


@dataclass
class RunTimings:
    """One run's per-stage spans, in milliseconds from the first request.

    Spans are wall-clock, not the published `duration_ms`, so a gap between two
    events is visible instead of being absorbed into whichever step contains it.
    """

    total_ms: float
    ttft_ms: float | None
    spans: dict[str, float] = field(default_factory=dict)
    steps: list[tuple[str, float]] = field(default_factory=list)
    status: str = "unknown"

    def add(self, stage: str, ms: float) -> None:
        self.spans[stage] = self.spans.get(stage, 0.0) + ms

    def residual(self, outer: str) -> float:
        """What the outer step contains that no labelled sub-step accounted for."""
        inner = sum(
            value for stage, value in self.spans.items() if stage not in OUTER_LABELS.values()
        )
        return max(0.0, self.spans.get(outer, 0.0) - inner)


def _ts_ms(event: dict[str, Any]) -> float | None:
    raw = event.get("ts")
    if not isinstance(raw, str):
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(raw).timestamp() * 1000
    return None


def attribute(events: list[dict[str, Any]], *, client_ttft_ms: float | None = None) -> RunTimings:
    """Turn one run's SSE events into per-stage spans. Pure: the clock is the
    events' own `ts` (stamped by the RunBus on publish), so the same input
    always gives the same table. `client_ttft_ms` is measured by the caller
    from the moment it sent the request, which is the figure ADR-003's targets
    are stated against."""
    timings = RunTimings(total_ms=0.0, ttft_ms=client_ttft_ms)
    open_steps: dict[str, list[float]] = {}
    first_ts: float | None = None
    for event in events:
        ts = _ts_ms(event)
        if ts is not None and first_ts is None:
            first_ts = ts
        kind = str(event.get("type", ""))
        label = str(event.get("label", ""))
        if kind == "step.started":
            open_steps.setdefault(label, []).append(ts if ts is not None else 0.0)
            timings.steps.append((label, ts if ts is not None else 0.0))
        elif kind == "step.completed":
            stack = open_steps.get(label)
            if not stack:
                continue
            started = stack.pop(0)
            if ts is None:
                # No ts on the event: fall back to the duration the step
                # published rather than dropping the stage.
                timings.add(stage_for_label(label), float(event.get("duration_ms") or 0))
                continue
            timings.add(stage_for_label(label), ts - started)
        elif kind in {"run.completed", "run.failed", "run.cancelled"}:
            timings.status = kind
            if ts is not None and first_ts is not None:
                timings.total_ms = ts - first_ts
            break
    if timings.total_ms == 0.0 and events:
        last = _ts_ms(events[-1])
        if last is not None and first_ts is not None:
            timings.total_ms = last - first_ts
    return timings


def _p50(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def summarise(
    runs: list[RunTimings], *, residual_of: tuple[str, ...] = ("retrieve",)
) -> list[StageStat]:
    """p50 and worst per stage across runs, with each stage's share of the p50 total.

    The denominator is the median total, so a stage's share is read against a
    typical run rather than the sum of every run.
    """
    totals = [run.total_ms for run in runs if run.total_ms > 0]
    if not totals:
        return []
    p50_total = _p50(totals)
    stages: dict[str, list[float]] = {}
    for run in runs:
        for stage, value in run.spans.items():
            stages.setdefault(stage, []).append(value)
        for outer in residual_of:
            if outer in run.spans:
                stages.setdefault(f"{outer} (unlabelled)", []).append(run.residual(outer))
    stats = [
        StageStat(
            stage=stage,
            p50_ms=_p50(values),
            worst_ms=max(values),
            share=(sum(values) / len(values)) / p50_total if p50_total else 0.0,
        )
        for stage, values in stages.items()
    ]
    ttfts = [run.ttft_ms for run in runs if run.ttft_ms is not None]
    if ttfts:
        stats.append(
            StageStat(
                stage="time to first token (client)",
                p50_ms=_p50(ttfts),
                worst_ms=max(ttfts),
                share=_p50(ttfts) / p50_total if p50_total else 0.0,
            )
        )
    stats.append(
        StageStat(
            stage="TOTAL (first token -> run end)",
            p50_ms=p50_total,
            worst_ms=max(totals),
            share=1.0,
        )
    )
    return sorted(stats, key=lambda stat: -stat.p50_ms)


def render(stats: list[StageStat]) -> str:
    lines = [
        "| stage | p50 ms | worst ms | share |",
        "| --- | --- | --- | --- |",
    ]
    for stat in stats:
        lines.append(
            f"| {stat.stage} | {stat.p50_ms:.0f} | {stat.worst_ms:.0f} | {stat.share * 100:.1f}% |"
        )
    return "\n".join(lines)


async def _run_once(
    client: httpx.AsyncClient, token: str, chat_id: str, message: str
) -> tuple[list[dict[str, Any]], float | None, str]:
    """One turn, keeping every SSE event and the client-side time to first token."""
    headers = {"Authorization": f"Bearer {token}"}
    sent_at = time.monotonic()
    created = await client.post(
        f"/chats/{chat_id}/runs",
        headers=headers,
        json={"message": message, "mode": "auto", "source": "upload"},
    )
    if created.status_code != 201:
        return [], None, f"run failed: {created.status_code}"
    run_id = created.json()["run_id"]
    events: list[dict[str, Any]] = []
    ttft_ms: float | None = None
    async with client.stream(
        "GET", f"/runs/{run_id}/stream", headers=headers, params={"after_seq": 0}
    ) as response:
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            events.append(event)
            kind = str(event.get("type"))
            if kind == "answer.delta" and ttft_ms is None:
                ttft_ms = (time.monotonic() - sent_at) * 1000
            if kind in {"run.completed", "run.failed", "run.cancelled"}:
                break
    return events, ttft_ms, run_id


async def probe(
    questions: list[str],
    *,
    runs: int,
    pace: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[RunTimings]:
    timeout = httpx.Timeout(
        connect=30.0, read=smoke_chat.RUN_TIMEOUT_SECONDS, write=60.0, pool=60.0
    )
    collected: list[RunTimings] = []
    async with httpx.AsyncClient(base_url=smoke_chat.API_URL, timeout=timeout) as client:
        email, password = await acceptance.eval_sign_in(client)

        async def token() -> str:
            response = await client.post("/auth/login", json={"email": email, "password": password})
            if response.status_code != 200:
                raise SystemExit(f"login failed mid-run: {response.status_code}")
            return str(response.json()["access_token"])

        for index, question in enumerate(questions, start=1):
            for run in range(1, runs + 1):
                headers = {"Authorization": f"Bearer {await token()}"}
                chat = await client.post("/chats", headers=headers, json={"title": None})
                chat_id = str(chat.json()["id"])
                events, ttft_ms, status = await _run_once(client, await token(), chat_id, question)
                timings = attribute(events, client_ttft_ms=ttft_ms)
                timings.status = timings.status if timings.status != "unknown" else str(status)
                collected.append(timings)
                print(
                    f"  [{index}/{len(questions)}] run {run}: {timings.total_ms:.0f} ms "
                    f"({timings.status}) — {question[:60]}",
                    flush=True,
                )
                if pace and not (index == len(questions) and run == runs):
                    await sleep(pace)
    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=10, help="how many questions (default 10)")
    parser.add_argument("--runs", type=int, default=2, help="runs per question (default 2)")
    parser.add_argument("--pace", type=float, default=0.0, help="seconds between runs")
    parser.add_argument("--set-file", type=Path, default=None)
    parser.add_argument(
        "--out", type=Path, default=None, help="where to write the JSON (default .data/lane-b)"
    )
    args = parser.parse_args()

    dataset = json.loads((args.set_file or SET_FILE).read_text())
    # One turn per item, the last one: the questions a user actually sends.
    questions = [str(item["turns"][-1]) for item in dataset["items"]][: args.questions]
    if not questions:
        raise SystemExit("no questions in the set")

    print(f"probing {len(questions)} questions x {args.runs} runs\n", flush=True)
    runs = asyncio.run(probe(questions, runs=args.runs, pace=args.pace))

    stats = summarise(runs)
    print("\n" + render(stats))

    out_dir = args.out.parent if args.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out or out_dir / f"probe-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    with contextlib.suppress(OSError):
        out.write_text(
            json.dumps(
                {
                    "questions": questions,
                    "runs": args.runs,
                    "stages": [
                        {
                            "stage": stat.stage,
                            "p50_ms": stat.p50_ms,
                            "worst_ms": stat.worst_ms,
                            "share": stat.share,
                        }
                        for stat in stats
                    ],
                    "per_run": [
                        {
                            "status": run.status,
                            "total_ms": run.total_ms,
                            "ttft_ms": run.ttft_ms,
                            "spans": run.spans,
                        }
                        for run in runs
                    ],
                },
                indent=2,
            )
        )
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
