"""Item 5: re-measure ADR-003's targets over real HTTP, same method as lane B.

Lane B item 7 measured the client-side targets on `main` and reported four of
them NOT met (answers p50 6614 ms against a 5 s target; answers p95 18.8 s
against 8 s; declines p95 12.7 s against 10 s; a 7068 ms trace gap against 2 s).
This script repeats that measurement on the current branch, **the same
question sets in the same classes**, so the two numbers are comparable and the
difference is the branch rather than the method.

Two classes, and why they are not the obvious choice:

* **answers** — acceptance book questions, items 4 onward, skipping the
  greeting and catalog items that never reach retrieval. `resolve_scope` gives
  an HTTP chat the `Shared` library (eleven novels), so a book question is
  answerable over HTTP.
* **declines** — the 12 entity-mismatch items plus fast20's 8 should-abstain
  items. Over HTTP these decline because the corpus documenting those entities
  is private to the eval user and out of an HTTP chat's scope; that is the
  honest outcome for an empty scope, and it is the class the results note
  measured. The per-item `scope_corpus` isolation is only reachable through
  `evals.runner`, not over HTTP — so this is "declines over HTTP", not
  "entity-mismatch over HTTP", and the difference is stated in the output.

TTFT is measured from the moment the run request is sent to the first
`answer.delta` arriving at the client — the number ADR-003 states its targets
against — and the gap is measured the same way KI-66's test measures it, in
**arrival time at the client**, so a publish that is stamped on time but
arrives late still reads as late.

Usage (stack up, eval account, real keys):

    EVAL_USER_EMAIL=... EVAL_USER_PASSWORD=... \\
      uv run python scripts/probe_adr003_targets.py

Latency is measured ALONE, with the laptop awake (`caffeinate -dims`).
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from scripts import acceptance as acceptance
from scripts import smoke_chat as smoke_chat

ROOT = Path(__file__).resolve().parents[3]
BOOKS = ROOT / "evals" / "acceptance" / "books.json"
ENTITY_MISMATCH = ROOT / "evals" / "entity_mismatch" / "items.json"
SEED = ROOT / "evals" / "seed" / "items.json"
OUT_DIR = ROOT / ".data" / "lane-b2"

TERMINAL = {"run.completed", "run.failed", "run.cancelled"}


def load_root_env() -> None:
    """Put the root `.env` and the app `.env` into the environment.

    `acceptance.eval_sign_in` needs `EVAL_USER_EMAIL` and
    `EVAL_USER_PASSWORD`, and it reads them from the process environment.
    Sourcing only the root `.env` loses them — they live in `apps/api/.env` —
    and the probe then refuses to sign up a throwaway user rather than score a
    library the eval never uses. That refusal is correct behaviour and an
    unhelpful way to discover the sourcing rule.

    `setdefault`, not assignment: a variable the caller exported on purpose
    still wins.
    """
    for candidate in (
        ROOT / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# ADR-003 §2, as the results note quoted them.
TARGETS = {
    "answers_p50_ms": 5_000,
    "answers_p95_ms": 8_000,
    "declines_p95_ms": 10_000,
    "max_gap_ms": 2_000,
}

# The run limiter is 60 per 60 s per address (`RATE_LIMIT_RUN`), and a turn
# costs two of those requests. Back past the window on a 429 rather than
# counting the harness's own pacing mistake as a dead run.
RUN_429_RETRIES = 3
RUN_429_WINDOW_SECONDS = 65.0
# Between turns, so 40 turns stay inside the window without a single 429.
DEFAULT_PACE_SECONDS = 2.0


def measured_sha() -> str:
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
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown"


def _items(path: Path) -> list[dict[str, Any]]:
    payload: Any = json.loads(path.read_text())
    items: list[dict[str, Any]] = payload["items"] if isinstance(payload, dict) else payload
    return items


def answer_questions(count: int) -> list[str]:
    """Items 4+ of the acceptance books: the ones that reach retrieval.

    Items 0-3 are a greeting, a thanks and catalog questions, which take a
    fast path and never reach the retrieval the target is about — the same
    exclusion the lane B probe set made and records.
    """
    return [str(item["turns"][-1]) for item in _items(BOOKS)[4:]][0:count]


def decline_questions(count: int) -> list[str]:
    """The entity-mismatch set, then fast20's should-abstain items."""
    out = [str(item["question"]) for item in _items(ENTITY_MISMATCH)]
    seed = json.loads(SEED.read_text())
    fast20 = set(seed.get("fast20_ids", []))
    abstain = [
        str(item["question"])
        for item in _items(SEED)
        if item.get("should_abstain") and item["id"] in fast20
    ]
    return (out + abstain)[0:count]


@dataclass
class Turn:
    question: str
    klass: str
    status: str
    # Set from the `abstain` event, which is the pipeline's own statement that
    # the run declined. A decline also streams deltas, so delta arrival is NOT
    # the signal.
    declined: bool = False
    ttft_ms: float | None = None
    total_ms: float = 0.0
    # The user-waiting silence: the first event's arrival to the first token.
    wait_ms: float = 0.0
    # The largest gap in the run, and where it was. Split at the first token
    # is NOT done here: the target is about the wait, so post-delivery
    # silences are reported separately rather than folded in.
    gap_before_token_ms: float = 0.0
    gap_where: str = ""
    gap_post_delivery_ms: float = 0.0
    steps: dict[str, float] = field(default_factory=dict)

    @property
    def unlabelled_gap_ms(self) -> float:
        """The largest silence in the wait with no step open across it."""
        return self.gap_before_token_ms


async def _one(
    client: httpx.AsyncClient, headers: dict[str, str], question: str, klass: str
) -> Turn:
    sent_at = time.monotonic()
    chat = await client.post("/chats", headers=headers, json={"title": None})
    chat_id = str(chat.json()["id"])
    created: httpx.Response | None = None
    for _attempt in range(1, RUN_429_RETRIES + 1):
        created = await client.post(
            f"/chats/{chat_id}/runs",
            headers=headers,
            json={"message": question, "mode": "auto", "source": "upload"},
        )
        if created.status_code != 429:
            break
        # `RATE_LIMIT_RUN` is 60 per 60 s per address and this script issues
        # two requests a turn (a chat, then a run), so an un-paced 40-turn
        # probe walks into it. A 429 here is the harness outrunning the
        # limiter, NOT a product failure, and the first draft counted those
        # as `run_failed_http_429` and reported 29 of 40 as dead runs. Waited
        # out rather than dropped: back off past the window, then retry.
        await asyncio.sleep(RUN_429_WINDOW_SECONDS)
    assert created is not None
    if created.status_code != 201:
        return Turn(question, klass, f"run_failed_http_{created.status_code}")

    run_id = created.json()["run_id"]
    turn = Turn(question, klass, "unknown")
    arrivals: list[tuple[float, str, str]] = []  # (arrival, type, label)
    first_token_at: float | None = None
    open_at: dict[str, float] = {}
    start_at = time.monotonic()

    async with client.stream(
        "GET", f"/runs/{run_id}/stream", headers=headers, params={"after_seq": 0}
    ) as response:
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            now = time.monotonic()
            kind = str(event.get("type", ""))
            label = str(event.get("label", ""))
            arrivals.append((now, kind, label))

            if len(arrivals) == 1:
                turn.wait_ms = (now - start_at) * 1000
            if kind == "step.started":
                open_at.setdefault(label, now)
            elif kind == "step.completed":
                opened = open_at.pop(label, None)
                if opened is not None:
                    turn.steps[label] = turn.steps.get(label, 0.0) + (now - opened) * 1000
                open_at.clear()
            elif kind == "abstain":
                # THE classifier. A decline streams an `answer.delta` too —
                # the prose "I could not find enough evidence to answer that
                # question" — so "did a delta arrive" says nothing about
                # whether the run answered. The first draft used that and
                # reported all 20 declines as ANSWERED, which made the
                # declines row read "n/a" and quietly dropped a third of the
                # measurement.
                turn.declined = True
            elif kind == "answer.delta" and first_token_at is None:
                first_token_at = now
                turn.ttft_ms = (now - sent_at) * 1000
            elif kind in TERMINAL:
                turn.status = kind
                turn.total_ms = (now - start_at) * 1000
                break

    # The longest silence inside the wait that no step was open across, and
    # the longest one after the token. Splitting at the first delta is the
    # point: a run ends with the reviewer re-reading every claim, and a
    # silence after the user has their text is not a silence they waited
    # through.
    for i in range(1, len(arrivals)):
        prev_at, prev_kind, prev_label = arrivals[i - 1]
        now, kind, label = arrivals[i]
        was_open = prev_kind == "step.started"
        gap = (now - prev_at) * 1000
        where = f"{prev_label or prev_kind} -> {label or kind}"
        if first_token_at is None or now <= first_token_at:
            if gap > turn.gap_before_token_ms and not was_open:
                turn.gap_before_token_ms = gap
                turn.gap_where = where
        elif gap > turn.gap_post_delivery_ms:
            turn.gap_post_delivery_ms = gap
    return turn


async def run_all(answers: list[str], declines: list[str], pace: float) -> list[Turn]:
    load_root_env()
    timeout = httpx.Timeout(
        connect=30.0, read=smoke_chat.RUN_TIMEOUT_SECONDS, write=60.0, pool=60.0
    )
    turns: list[Turn] = []
    async with httpx.AsyncClient(base_url=smoke_chat.API_URL, timeout=timeout) as client:
        email, password = await acceptance.eval_sign_in(client)
        # One login, one token: RATE_LIMIT_LOGIN is 10/60s per address and a
        # token per turn spends the budget on logins instead of on runs.
        login = await client.post("/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            raise SystemExit(f"login failed: {login.status_code}")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for klass, questions in (("answer", answers), ("decline", declines)):
            for index, question in enumerate(questions, start=1):
                turn = await _one(client, headers, question, klass)
                turns.append(turn)
                print(
                    f"  {klass:<8} [{index}/{len(questions)}] "
                    f"ttft {turn.ttft_ms or 0:>7.0f} ms  "
                    f"gap {turn.gap_before_token_ms:>7.0f} ms  "
                    f"{'declined' if turn.declined else 'answered'} "
                    f"({turn.status}) — {question[:45]}",
                    flush=True,
                )
                if pace:
                    await asyncio.sleep(pace)
    return turns


def _p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(q * (len(ordered) - 1)))
    return ordered[index]


def report(turns: list[Turn]) -> str:
    answered = [t for t in turns if t.klass == "answer" and not t.declined]
    declined = [t for t in turns if t.klass == "decline" and t.declined]
    failed = [t for t in turns if t.status != "run.completed"]
    ttft_a = [t.ttft_ms for t in answered if t.ttft_ms is not None]
    ttft_d = [t.ttft_ms for t in declined if t.ttft_ms is not None]
    gaps = [t.gap_before_token_ms for t in turns]
    post = [t.gap_post_delivery_ms for t in turns]

    def verdict(value: float | None, target: float) -> str:
        if value is None:
            return "n/a"
        return "MET" if value <= target else "**NOT MET**"

    lines = [
        "| ADR-003 target | lane B (`main`) | this branch | met? |",
        "| --- | --- | --- | --- |",
    ]
    rows = [
        ("answers p50 ≤ 5 s", "6614 ms", _p(ttft_a, 0.5), TARGETS["answers_p50_ms"]),
        ("answers p95 ≤ 8 s", "18794 ms", _p(ttft_a, 0.95), TARGETS["answers_p95_ms"]),
        ("declines p95 ≤ 10 s", "12655 ms", _p(ttft_d, 0.95), TARGETS["declines_p95_ms"]),
        ("no trace gap > 2 s", "7068 ms", max(gaps, default=0.0), TARGETS["max_gap_ms"]),
    ]
    for label, before, value, target in rows:
        shown = "n/a" if value is None else f"{value:.0f} ms"
        lines.append(f"| {label} | {before} | {shown} | {verdict(value, target)} |")

    lines += [
        "",
        f"- **class sizes:** {len(answered)} answered, {len(declined)} declined, "
        f"{len(failed)} run(s) did not complete",
        "- **failure detail:** "
        + (", ".join(f"{t.status} on {t.question[:40]!r}" for t in failed) or "none"),
        "- **declines p50:** "
        + (f"{_p(ttft_d, 0.5):.0f} ms" if _p(ttft_d, 0.5) is not None else "n/a"),
        f"- **largest post-delivery silence (not a target):** {max(post, default=0.0):.0f} ms",
        f"- **worst pre-token gap, and where:** "
        f"{max((t.gap_before_token_ms for t in turns), default=0.0):.0f} ms"
        + (f" ({max(turns, key=lambda t: t.gap_before_token_ms).gap_where})" if turns else ""),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=int, default=20)
    parser.add_argument("--declines", type=int, default=20)
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS)
    args = parser.parse_args()

    answers = answer_questions(args.answers)
    declines = decline_questions(args.declines)
    sha = measured_sha()
    print(
        f"measuring SHA {sha} over HTTP: {len(answers)} answers, {len(declines)} declines\n",
        flush=True,
    )
    turns = asyncio.run(run_all(answers, declines, args.pace))
    print("\n" + report(turns))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = OUT_DIR / f"adr003-{stamp}-{sha}.json"
    path.write_text(json.dumps({"sha": sha, "turns": [t.__dict__ for t in turns]}, indent=2))
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
