"""Item 4: where the time really goes — the generator.

Lane B's measurement found client TTFT at p50 6.8 s while `retrieve` was
2.0 s. The stage that owns most of the wait was never the one lane B
optimised, so before changing anything this script measures what the
generator itself costs and what, if anything, is on our side of it.

Per run it records, from the real HTTP/SSE stream:

* **client TTFT** — POST sent -> first `answer.delta`, the number ADR-003
  states its targets against;
* **generate start -> first token** — the generator's own share, split out of
  the client number by the `step.started: generate` event  added;
* **input tokens sent to the generator** (`tokens_in` on the metrics event)
  and the **model**, because a latency question is not answerable without
  them;
* **what sits before the first token and after it**, as separate spans, so
  "the generator is slow" cannot quietly mean "we sent it too much" or
  "something sequential runs in front of it".

It then measures the **same model at the same token count, called raw** —
one direct `stream_completion` with no retrieval, no rerank, no reviewer —
which is the only way to separate our overhead from the model's own latency
at that input size. The difference between the run's generate-to-first-token
and the raw call's is what this script is looking for.

Reads the same SSE stream the browser reads; no monkeypatching of the hot
path. Every stage number comes from a `step.started`/`step.completed` pair
the pipeline published itself.

Usage (needs the local stack up, the eval account, and real provider keys):

    EVAL_USER_EMAIL=... EVAL_USER_PASSWORD=... \\
      uv run python scripts/probe_generator_latency.py --questions 10 --runs 2

Latency is measured ALONE (`docs/conventions/agents.md`): run it with
nothing else on the machine, with the laptop awake (`caffeinate -dims`), and
note any sleep in the report.

Writes `.data/lane-b2/generator-<timestamp>-<sha>.json` beside the printed
tables so the numbers can be re-read without re-running.
"""

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from scripts import acceptance as acceptance
from scripts import smoke_chat as smoke_chat

SET_FILE = Path(__file__).resolve().parents[3] / "evals" / "acceptance" / "books.json"
OUT_DIR = Path(__file__).resolve().parents[3] / ".data" / "lane-b2"

TERMINAL = {"run.completed", "run.failed", "run.cancelled"}


def load_root_env() -> None:
    """Put the root `.env` into the environment, without overriding the shell.

    `config.py` reads `env_file=".env"` relative to the working directory, and
    this script runs from `apps/api`, where `.env` holds only the eval
    account's credentials. The provider key lives in the root `.env`. Without
    this the raw control call dies with `OpenRouterException: No cookie auth
    credentials found` — which is a harness fault dressed as a provider fault,
    and the same trap `scripts/eval_gate_local.sh` documents for the gate.

    `setdefault`, not assignment: a variable the caller exported on purpose
    still wins.
    """
    root_env = Path(__file__).resolve().parents[3] / ".env"
    if not root_env.exists():
        return
    for line in root_env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def measured_sha() -> str:
    """The commit these numbers measure. Read from git, never assumed."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            cwd=Path(__file__).resolve().parents[3],
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown"


@dataclass
class Run:
    """One turn, with the clock split where the questions actually are."""

    question: str
    status: str
    model: str = ""
    client_ttft_ms: float | None = None
    # Client-send -> `step.started: generate`. Everything we do before the
    # generator is called.
    pre_generate_ms: float | None = None
    # `step.started: generate` -> first `answer.delta`. The generator's own
    # wait for its first token, including our connection setup inside it.
    generate_to_first_token_ms: float | None = None
    # First token -> `step.completed: generate`: the rest of the stream.
    rest_of_generation_ms: float | None = None
    # First token -> run end: the reviewer, scoring, persistence, title.
    post_delivery_ms: float | None = None
    total_ms: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    # Per-stage durations the pipeline published, for context in the report.
    steps: dict[str, float] = field(default_factory=dict)
    largest_gap_ms: float = 0.0
    largest_gap_where: str = ""


def _ts_ms(event: dict[str, Any]) -> float | None:
    raw = event.get("ts")
    if not isinstance(raw, str):
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(raw).timestamp() * 1000
    return None


def attribute(
    question: str, events: list[dict[str, Any]], *, sent_at: float, client_ttft_ms: float | None
) -> Run:
    """Pure: the clock is the events' own `ts` plus the two client-side marks.

    `sent_at` is a `time.monotonic()` reading, so the two client-side spans
    are computed from it and every server-side span from `ts`; the two clocks
    are never mixed inside one span.
    """
    run = Run(question=question, status="unknown", client_ttft_ms=client_ttft_ms)

    stamps: list[tuple[float, dict[str, Any]]] = []
    for event in events:
        ts = _ts_ms(event)
        if ts is not None:
            stamps.append((ts, event))

    # The largest silence between two consecutive events, named. Reported
    # because it is the user-visible wait and no stage label covers it.
    for (a_ts, a), (b_ts, b) in pairwise(stamps):
        gap = b_ts - a_ts
        if gap > run.largest_gap_ms:
            run.largest_gap_ms = gap
            run.largest_gap_where = (
                f"{a.get('label') or a.get('type')} -> {b.get('label') or b.get('type')}"
            )

    open_steps: dict[str, list[float]] = {}
    generate_start: float | None = None
    first_token: float | None = None
    generate_end: float | None = None
    for ts, event in stamps:
        kind = str(event.get("type", ""))
        label = str(event.get("label", ""))
        if kind == "run.started":
            run.model = str(event.get("model", ""))
        elif kind == "step.started":
            open_steps.setdefault(label, []).append(ts)
            if label == "generate":
                generate_start = ts
        elif kind == "step.completed":
            stack = open_steps.get(label)
            if stack:
                run.steps[label] = run.steps.get(label, 0.0) + (ts - stack.pop(0))
            if label == "generate":
                generate_end = ts
        elif kind == "answer.delta" and first_token is None:
            first_token = ts
        elif kind == "metrics":
            run.tokens_in = event.get("tokens_in")
            run.tokens_out = event.get("tokens_out")
        elif kind in TERMINAL:
            run.status = kind
            if stamps:
                run.total_ms = ts - stamps[0][0]
            break

    if generate_start is not None and first_token is not None:
        run.generate_to_first_token_ms = first_token - generate_start
        run.pre_generate_ms = generate_start - (stamps[0][0] if stamps else generate_start)
    if first_token is not None and generate_end is not None:
        run.rest_of_generation_ms = generate_end - first_token
        run.post_delivery_ms = generate_end - first_token
    return run


async def _one_run(
    client: httpx.AsyncClient, headers: dict[str, str], chat_id: str, question: str
) -> tuple[list[dict[str, Any]], float, float | None]:
    sent_at = time.monotonic()
    created = await client.post(
        f"/chats/{chat_id}/runs",
        headers=headers,
        json={"message": question, "mode": "auto", "source": "upload"},
    )
    if created.status_code != 201:
        return [], sent_at, None
    run_id = created.json()["run_id"]
    events: list[dict[str, Any]] = []
    ttft: float | None = None
    async with client.stream(
        "GET", f"/runs/{run_id}/stream", headers=headers, params={"after_seq": 0}
    ) as response:
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            events.append(event)
            if event.get("type") == "answer.delta" and ttft is None:
                ttft = (time.monotonic() - sent_at) * 1000
            if event.get("type") in TERMINAL:
                break
    return events, sent_at, ttft


async def probe(questions: list[str], *, runs: int, pace: float) -> list[Run]:
    timeout = httpx.Timeout(
        connect=30.0, read=smoke_chat.RUN_TIMEOUT_SECONDS, write=60.0, pool=60.0
    )
    collected: list[Run] = []
    async with httpx.AsyncClient(base_url=smoke_chat.API_URL, timeout=timeout) as client:
        email, password = await acceptance.eval_sign_in(client)

        # Log in ONCE and reuse the token. `RATE_LIMIT_LOGIN` is 10 per 60 s
        # per address, and a token per turn spends that budget on logins
        # rather than on runs — the first draft of this script logged in
        # twice a turn and died at 429 on the third question. The token is a
        # JWT, not a per-request nonce, so nothing is weakened by reusing it.
        login = await client.post("/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            raise SystemExit(f"login failed: {login.status_code}")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for index, question in enumerate(questions, start=1):
            for run_index in range(1, runs + 1):
                chat = await client.post("/chats", headers=headers, json={"title": None})
                chat_id = str(chat.json()["id"])
                events, sent_at, ttft = await _one_run(client, headers, chat_id, question)
                measured = attribute(question, events, sent_at=sent_at, client_ttft_ms=ttft)
                collected.append(measured)
                print(
                    f"  [{index}/{len(questions)}] run {run_index}: "
                    f"ttft {measured.client_ttft_ms or 0:.0f} ms, "
                    f"gen->token {measured.generate_to_first_token_ms or 0:.0f} ms, "
                    f"in {measured.tokens_in} tok ({measured.status}) — "
                    f"{question[:50]}",
                    flush=True,
                )
                if pace and not (index == len(questions) and run_index == runs):
                    await asyncio.sleep(pace)
    return collected


async def raw_call(*, model: str, prompt_tokens: int, repeats: int) -> list[dict[str, float]]:
    """One raw streaming call at approximately `prompt_tokens` input size.

    This is the control: the same model, the same shape of request, with
    nothing of ours in front of it. What it costs is the floor. The
    pipeline's own generate-to-first-token above it is the part that is
    ours to attack — and if the two are close, the honest answer to "where
    does the time go" is "the model", not "us".
    """
    load_root_env()
    from providers.llm import stream_completion

    # Roughly the input size a real grounded answer sends, built out of
    # neutral filler so the control is about token count and not about the
    # content the model has to reason over.
    filler = "The quick brown fox jumps over the lazy dog. " * max(1, (prompt_tokens - 200) // 10)
    messages = [
        {"role": "system", "content": "Answer the question using only the sources."},
        {
            "role": "user",
            "content": f"{filler}\n\n[Question]\nWhat does the passage say?",
        },
    ]
    out: list[dict[str, float]] = []
    for index in range(1, repeats + 1):
        started = time.perf_counter()
        first: float | None = None
        count = 0
        async for _delta in stream_completion(
            litellm_model=model, messages=messages, metadata={"role": "generator"}
        ):
            count += 1
            if first is None:
                first = time.perf_counter()
        out.append(
            {
                "call": index,
                "to_first_token_ms": (first - started) * 1000 if first else 0.0,
                "total_ms": (time.perf_counter() - started) * 1000,
                "chunks": count,
            }
        )
        print(
            f"  raw call {index}/{repeats}: first token "
            f"{out[-1]['to_first_token_ms']:.0f} ms, total {out[-1]['total_ms']:.0f} ms",
            flush=True,
        )
    return out


def _p50(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def render(runs: list[Run], raw: list[dict[str, float]]) -> str:
    answered = [r for r in runs if r.client_ttft_ms is not None]

    def series(getter: Any) -> list[float]:
        return [v for v in (getter(r) for r in answered) if v is not None]

    rows = [
        ("client TTFT (ADR-003's number)", series(lambda r: r.client_ttft_ms)),
        ("everything before the generator", series(lambda r: r.pre_generate_ms)),
        ("generate start -> first token", series(lambda r: r.generate_to_first_token_ms)),
        ("first token -> generate end", series(lambda r: r.rest_of_generation_ms)),
        ("post-delivery (review, score, persist)", series(lambda r: r.post_delivery_ms)),
    ]
    lines = [
        "| measure | p50 ms | p95 ms | worst ms |",
        "| --- | --- | --- | --- |",
    ]
    for label, values in rows:
        if not values:
            continue
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        lines.append(f"| {label} | {_fmt(_p50(values))} | {p95:.0f} | {max(values):.0f} |")

    tokens = series(lambda r: float(r.tokens_in) if r.tokens_in is not None else None)
    models = sorted({r.model for r in runs if r.model})
    lines.append("")
    lines.append(f"- **model:** {', '.join(models) or 'n/a'}")
    lines.append(
        f"- **input tokens to the generator:** p50 {_fmt(_p50(tokens))}, worst {max(tokens):.0f}"
        if tokens
        else "- **input tokens:** n/a"
    )
    worst_gap = max((r.largest_gap_ms for r in answered), default=0)
    lines.append(f"- **largest unlabelled gap:** {worst_gap:.0f} ms")
    if raw:
        raw_first = [entry["to_first_token_ms"] for entry in raw]
        pipeline = series(lambda r: r.generate_to_first_token_ms)
        lines.append(
            f"- **raw call, same model, ~{_fmt(_p50(tokens))} input tokens:** "
            f"first token p50 {_fmt(_p50(raw_first))} ms"
        )
        if pipeline:
            pipeline_p50 = _p50(pipeline) or 0.0
            gap = pipeline_p50 - (_p50(raw_first) or 0.0)
            lines.append(
                f"- **our overhead at the generator (pipeline p50 minus raw p50):** {gap:+.0f} ms"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=10)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--pace", type=float, default=0.0)
    parser.add_argument("--set-file", type=Path, default=None)
    parser.add_argument("--raw-calls", type=int, default=3)
    parser.add_argument("--skip-raw", action="store_true")
    args = parser.parse_args()

    dataset = json.loads((args.set_file or SET_FILE).read_text())
    questions = [str(item["turns"][-1]) for item in dataset["items"]][: args.questions]
    if not questions:
        raise SystemExit("no questions in the set")

    sha = measured_sha()
    print(f"measuring SHA {sha}, {len(questions)} questions x {args.runs} runs\n", flush=True)
    runs = asyncio.run(probe(questions, runs=args.runs, pace=args.pace))

    answered = [r for r in runs if r.client_ttft_ms is not None]
    tokens = [float(r.tokens_in) for r in answered if r.tokens_in]
    p50_tokens = int(_p50(tokens) or 4000)
    model = answered[0].model if answered and answered[0].model else ""
    model_id = f"openrouter/{model}" if model and not model.startswith("openrouter/") else model

    raw: list[dict[str, float]] = []
    if not args.skip_raw and model_id:
        print(f"\nraw control calls on {model_id}, ~{p50_tokens} input tokens\n", flush=True)
        raw = asyncio.run(
            raw_call(model=model_id, prompt_tokens=p50_tokens, repeats=args.raw_calls)
        )

    print("\n" + render(runs, raw))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = OUT_DIR / f"generator-{stamp}-{sha}.json"
    path.write_text(
        json.dumps(
            {
                "sha": sha,
                "measured_at": stamp,
                "runs": [r.__dict__ for r in runs],
                "raw_calls": raw,
            },
            indent=2,
        )
    )
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
