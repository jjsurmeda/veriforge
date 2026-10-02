"""Usability acceptance runner (`make acceptance`): replays
evals/acceptance/books.json against the live local stack and classifies the
last turn of each item.

Reuses smoke_chat's sign-up / run_turn / SSE reading (same HTTP surface as
`make smoke`); one fresh chat per item, turns in order, source "upload",
mode "auto". Writes raw results to .data/acceptance/<timestamp>.json.

The run user is moved to the seeded `internal-eval` plan through the admin
API before the first turn: a full run costs ~310k quota credits (KI-20) and
`free` allows 200k per 5 h, so runs used to raise `free`'s limit by hand and
restore it. `free` and `pro` are never mutated here. Needs `ADMIN_EMAIL` /
`ADMIN_PASSWORD` (`make seed-admin`); without them the run stops rather than
falling back to editing the database.

Usage: uv run python scripts/acceptance.py [id1,id2,...] [--pace SECONDS].

Pacing is opt-in: `--pace N` sleeps N seconds between items (skip after
smalltalk items and after the last one) for free-model rate limits
(OpenRouter free tier caps free-model requests at 20/min); the default of 0
runs back-to-back, which paid models can afford.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from scripts import smoke_chat as smoke_chat
from textkit import detect_language

SET_FILE = Path(__file__).resolve().parents[3] / "evals" / "acceptance" / "books.json"
OUT_DIR = Path(__file__).resolve().parents[3] / ".data" / "acceptance"

# Seeded by migration 0014 with headroom for a full run. Never `free` or `pro`:
# those are the rows real users are on.
EVAL_PLAN_NAME = "internal-eval"

NO_ADMIN = (
    "acceptance needs admin credentials to move its run user onto the "
    f"{EVAL_PLAN_NAME} plan: set ADMIN_EMAIL and ADMIN_PASSWORD in .env "
    "(`make seed-admin` creates the account). Refusing to raise a plan's "
    "credit limit instead — that mutates the row real users are on."
)

# "Says plainly it's not in the sources" — generous on purpose: batch B owns
# the exact wording, this only has to recognise the shape.
NOT_IN_SOURCES = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"not (?:in|among|covered|found|mentioned|included) (?:the|my|your|these|your) ",
        r"(?:don'?t|do not|cannot|can'?t|couldn'?t|doesn'?t|does not) "
        r"(?:find|have|contain|see|show)",
        r"(?:isn'?t|is not|aren'?t|are not|wasn'?t) (?:in|among|covered|included)",
        r"no (?:matching|relevant|such) ",
        r"not part of ",
        r"outside (?:the|my|your) ",
    )
)


def says_not_in_sources(answer: str) -> bool:
    return any(p.search(answer) for p in NOT_IN_SOURCES)


def _cited_documents(result: dict[str, Any]) -> list[str]:
    # citations are smoke_chat's "[n] Document p.x" strings
    return [c.split("] ", 1)[-1].split(" p.", 1)[0].split(" §", 1)[0] for c in result["citations"]]


def observed_class(item: dict[str, Any], result: dict[str, Any]) -> str:
    """What the run actually looked like, as one of the four classes."""
    answer = result["answer"]
    if result["message_status"] == "abstained" or result["status"] != "completed":
        return "not_in_sources"
    if result["citations"]:
        return "answer"
    if says_not_in_sources(answer):
        return "not_in_sources"
    lowered = answer.lower()
    if any(m.lower() in lowered for m in item.get("mention", [])):
        return "library"
    return "smalltalk"


def language_ok(item: dict[str, Any], result: dict[str, Any]) -> bool:
    """The reply must be in the language the user asked in.

    Expected language comes from the question, so the xl-* items — English
    questions about non-English books — expect English with no special case.
    An item may pin `"expect_language"` for a mixed-language turn the
    detector cannot read off the question.
    """
    expected = item.get("expect_language") or detect_language(item["turns"][-1])
    got = detect_language(result["answer"])
    # Undetectable on either side is not evidence of a mismatch.
    return expected is None or got is None or got == expected


def passes(item: dict[str, Any], result: dict[str, Any]) -> bool:
    expected = item["expect"]
    answer = result["answer"]
    lowered = answer.lower()
    completed = result["status"] == "completed" and result["message_status"] != "abstained"
    mentions = [m.lower() for m in item.get("mention", [])]
    # no mention list means there is nothing to check for
    mention_hit = True if not mentions else any(m in lowered for m in mentions)
    cite_hit = any(
        any(book.lower() in doc.lower() for book in item.get("cite", []))
        for doc in _cited_documents(result)
    )
    if not language_ok(item, result):
        return False
    if expected == "smalltalk":
        return completed and not result["citations"]
    if expected == "library":
        return completed and mention_hit
    if expected == "answer":
        return completed and bool(result["citations"]) and cite_hit and mention_hit
    if expected == "not_in_sources":
        plain = result["message_status"] == "abstained" or says_not_in_sources(answer)
        return plain and not result["citations"]
    return False


def failure_reason(item: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Why an item failed, so a language regression is not read as a
    retrieval or citation one."""
    if passes(item, result):
        return None
    if not language_ok(item, result):
        return "language_mismatch"
    expected = item["expect"]
    if expected == "answer" and not result["citations"]:
        return "no_citations"
    return "wrong_class_or_content"


async def assign_eval_plan(client: httpx.AsyncClient, run_email: str) -> str:
    """Put `run_email` on the seeded `internal-eval` plan, via the admin API.

    The product path, so the change is audited (`admin/service.py::update_user`)
    and needs no direct database access. Returns the plan name for the report.
    """
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(NO_ADMIN)

    login = await client.post("/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        raise SystemExit(
            f"admin login failed: {login.status_code} {login.text[:200]}\n"
            "run `make seed-admin` to create or promote the account"
        )
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    plans = await client.get("/admin/plans", headers=admin_headers)
    if plans.status_code != 200:
        raise SystemExit(f"admin plans lookup failed: {plans.status_code} {plans.text[:200]}")
    match = next((p for p in plans.json() if p["name"] == EVAL_PLAN_NAME), None)
    if match is None:
        raise SystemExit(
            f"no {EVAL_PLAN_NAME} plan (have: {[p['name'] for p in plans.json()]}); "
            "run the migrations (`docker compose restart api`)"
        )

    users = await client.get("/admin/users", headers=admin_headers)
    if users.status_code != 200:
        raise SystemExit(f"admin users lookup failed: {users.status_code} {users.text[:200]}")
    target = next((u for u in users.json() if u["email"] == run_email), None)
    if target is None:
        raise SystemExit(f"run user {run_email} not visible to the admin")

    patched = await client.patch(
        f"/admin/users/{target['id']}", headers=admin_headers, json={"plan_id": match["id"]}
    )
    if patched.status_code != 200:
        raise SystemExit(f"plan assignment failed: {patched.status_code} {patched.text[:200]}")
    assigned = patched.json().get("plan_id")
    if assigned != match["id"]:
        raise SystemExit(
            f"plan assignment did not take: plan_id is {assigned}, wanted {match['id']}"
        )
    return EVAL_PLAN_NAME


async def run(
    only: list[str] | None = None,
    *,
    pace: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    dataset = json.loads(SET_FILE.read_text())
    items = dataset["items"]
    if only:
        items = [i for i in items if i["id"] in only]
        missing = set(only) - {i["id"] for i in items}
        if missing:
            raise SystemExit(f"unknown item id(s): {sorted(missing)}")
        print(f"filtered to {len(items)} item(s): {[i['id'] for i in items]}\n")
    timeout = httpx.Timeout(
        connect=30.0, read=smoke_chat.RUN_TIMEOUT_SECONDS, write=60.0, pool=60.0
    )
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=smoke_chat.API_URL, timeout=timeout) as client:
        email = await smoke_chat.sign_up(client)
        # Before the first turn: the quota gate reserves on the first run, so
        # a later assignment would be too late for item 1's reserve.
        plan = await assign_eval_plan(client, email)
        print(f"run user {email} assigned to the {plan} plan\n")
        for item in items:

            async def play(item: dict[str, Any] = item) -> dict[str, Any]:
                token = await smoke_chat.sign_in(client, email)
                headers = {"Authorization": f"Bearer {token}"}
                chat = await client.post("/chats", headers=headers, json={"title": None})
                chat_id = str(chat.json()["id"])
                result: dict[str, Any] = {}
                for turn in item["turns"]:
                    fresh = await smoke_chat.sign_in(client, email)
                    result = await smoke_chat.run_turn(client, fresh, chat_id, turn)
                return result

            result = await play()
            # OpenRouter's free tier caps free-model requests at 20/min
            # account-wide; a failed run usually means this item hit the cap,
            # so wait out the window and measure the item once more.
            if str(result.get("status", "")).startswith("failed"):
                print(f"  {item['id']}: {result['status']}; retrying in 70s", flush=True)
                await asyncio.sleep(70)
                result = await play()
            got = observed_class(item, result)
            ok = passes(item, result)
            rows.append(
                {
                    "id": item["id"],
                    "expect": item["expect"],
                    "got": got,
                    "pass": ok,
                    "reason": failure_reason(item, result),
                    "q_language": detect_language(item["turns"][-1]),
                    "a_language": detect_language(result.get("answer") or ""),
                    "ttft_ms": result.get("ttft_ms"),
                    "sufficient": result.get("sufficient"),
                    "status": result.get("status"),
                    "message_status": result.get("message_status"),
                    "intent": result.get("intent"),
                    "answer": result.get("answer"),
                    "citations": result.get("citations"),
                    "steps": result.get("steps"),
                    "retrievals": result.get("retrievals"),
                    "turns": item["turns"],
                }
            )
            print(
                f"  {item['id']}: {got} "
                f"{'PASS' if ok else 'FAIL' + ' (' + str(rows[-1]['reason']) + ')'}",
                flush=True,
            )
            # Opt-in free-model pacing (--pace N; default 0 = no sleep),
            # skipped after smalltalk items and after the last item.
            if pace and item is not items[-1] and item["expect"] != "smalltalk":
                await sleep(pace)

    print("\n{| id | expected | got | pass | ttft ms | sufficient |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        scores = ",".join(f"{s:.2f}" for s in r["sufficient"] or []) or "-"
        print(
            f"| {r['id']} | {r['expect']} | {r['got']} | {'pass' if r['pass'] else 'FAIL'} "
            f"| {r['ttft_ms'] if r['ttft_ms'] is not None else '-'} | {scores} |"
        )

    ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
    p50 = int(statistics.median(ttfts)) if ttfts else 0
    per_class: dict[str, list[int]] = {}
    for r in rows:
        per_class.setdefault(r["expect"], []).append(1 if r["pass"] else 0)
    print(f"\npassed {sum(r['pass'] for r in rows)}/{len(rows)}; TTFT p50 {p50} ms")
    for cls, flags in per_class.items():
        print(f"  {cls}: {sum(flags)}/{len(flags)}")
    per_language: dict[str, list[int]] = {}
    for r in rows:
        per_language.setdefault(str(r["q_language"]), []).append(1 if r["pass"] else 0)
    print("  by question language:")
    for lang, flags in sorted(per_language.items()):
        print(f"    {lang}: {sum(flags)}/{len(flags)}")
    for reason in sorted({r["reason"] for r in rows if r["reason"]}):
        print(f"  failed {reason}: {[r['id'] for r in rows if r['reason'] == reason]}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}.json"
    out.write_text(json.dumps({"ran_at": stamp, "items": rows}, indent=2))
    print(f"raw results: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replay the acceptance set against the live stack."
    )
    parser.add_argument(
        "only",
        nargs="?",
        default=None,
        help="comma-separated item ids to run (default: all)",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="sleep this many seconds between items, for free-model rate "
        "limits (default: 0, no sleep)",
    )
    args = parser.parse_args()
    only = args.only.split(",") if args.only else None
    asyncio.run(run(only=only, pace=args.pace))
