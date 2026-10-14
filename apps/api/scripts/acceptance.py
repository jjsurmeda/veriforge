"""Usability acceptance runner (`make acceptance`): replays
evals/acceptance/books.json against the live local stack and classifies the
last turn of each item.

Reuses smoke_chat's run_turn / SSE reading (same HTTP surface as `make smoke`);
one fresh chat per item, turns in order, source "upload", mode "auto". Writes
raw results to .data/acceptance/<timestamp>.json.

**The run user is a fixed account, not a signup**. The books stay
`visibility='shared'` and every fresh user sees them, so the demo corpus is
unchanged; but the eval-only corpora (AW-2000 seed, counterfactual) are private
collections owned by `evals@veriforge.local`, and a throwaway signup has no
access to them — which is exactly the point of the move. Acceptance signs in as
that same account so it measures the Shared library through the same identity
the seed corpus is measured with. Only the identity persists: **every run still
creates a fresh chat per item**, so no item can see another's context.

Credentials are `EVAL_USER_EMAIL` / `EVAL_USER_PASSWORD`, the same shape as
`ADMIN_EMAIL` / `ADMIN_PASSWORD`; `make seed-eval-user` creates the account and
assigns the seeded `internal-eval` plan to it once. Without them the run stops
rather than signing up a user that cannot see what it is being scored on. The
books need no grant: `visibility='shared'` is in every user's scope.

Usage: uv run python scripts/acceptance.py [id1,id2,...] [--pace SECONDS].

Pacing is opt-in: `--pace N` sleeps N seconds between items (skip after
smalltalk items and after the last one) for free-model rate limits
(OpenRouter free tier caps free-model requests at 20/min); the default of 0
runs back-to-back, which paid models can afford.
"""

import argparse
import asyncio
import base64
import binascii
import json
import os
import re
import statistics
import sys
import time
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

# Seeded by migration 0014 with headroom for a full run. Assigned ONCE, to the
# persistent eval account, by `make seed-eval-user` — a per-run assignment would
# be a mutation of the same row 48 times, and the account outlives the run.
EVAL_PLAN_NAME = "internal-eval"

NO_EVAL_USER = (
    "acceptance signs in as the fixed eval account so it can see the eval "
    "corpora it is scored against. Set EVAL_USER_EMAIL and "
    "EVAL_USER_PASSWORD in .env, then run `make seed-eval-user` to create the "
    "account and put it on the "
    f"{EVAL_PLAN_NAME} plan. Refusing to sign up a throwaway user instead — it "
    "would score a library the eval never uses."
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


# Re-authenticate this long before the token's own `exp`, not after: a token
# that expires between the chat and its turn 401s, and the turn runner raises on
# that rather than retrying.
TOKEN_REFRESH_MARGIN_SECONDS = 60.0

# The runner's own pacing between re-logins, when the token's expiry cannot be
# read. 0 means "log in every time", which is the pre-2026-10-12 behaviour: slow
# but never wrong about expiry.
TOKEN_LIFETIME_FALLBACK_SECONDS = 0.0


def _token_lifetime(token: str) -> float:
    """Seconds until `token` expires, or the fallback when it cannot be read.

    Reads the JWT's own `exp` claim **without verifying the signature**, on
    purpose: this decides only when to spend another login against a rate limit,
    and the api is the one that decides whether a token is valid. A token this
    cannot read (an opaque token, a non-JWT shape) gets the fallback, so an
    unparseable token can never be mistaken for a long-lived one.

    `exp` is in seconds since the epoch and `time.monotonic()` is not, so the
    claim is compared against wall clock and converted here to a duration.
    """
    payload = token.split(".")
    if len(payload) != 3:
        return TOKEN_LIFETIME_FALLBACK_SECONDS
    try:
        padded = payload[1] + "=" * (-len(payload[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        expires_at = float(claims["exp"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return TOKEN_LIFETIME_FALLBACK_SECONDS
    remaining = expires_at - time.time()
    return remaining if remaining > 0 else TOKEN_LIFETIME_FALLBACK_SECONDS


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


def mentions_hit(item: dict[str, Any], answer: str) -> bool:
    """True when the answer states every string the item requires.

    `mention_all` is the ambiguity-item channel: the corpus answers the question
    two ways, so the item names **both** referents and an answer that names only
    one has not answered the question the corpus poses. These items are expected
    to fail today — P2's prompt change is what surfaces the ambiguity — and are
    marked `pending_p2` so they are reported separately and do not drag down the
    pass rate.
    """
    lowered = answer.lower()
    required = [str(m).lower() for m in item.get("mention_all", [])]
    optional = [str(m).lower() for m in item.get("mention", [])]
    optional += [str(m).lower() for m in item.get("alt_mention", [])]
    if required:
        return all(m in lowered for m in required) and (
            not optional or any(m in lowered for m in optional)
        )
    if not optional:
        return True
    return any(m in lowered for m in optional)


def forbids_hit(item: dict[str, Any], answer: str) -> str | None:
    """The first `forbid` string the answer contains, if any.

    For a counterfactual item (evals/counterfactual) the corpus states a
    deliberately altered fact, so the real-world value is the one a model
    produces from memory. `forbid` names it: an answer that states the
    document's value **and** the real one fails, because the product would have
    handed the user a figure its own sources contradict.

    Matched on word boundaries for the same reason `mention` should be: `IP68`
    must not fire on `IP69K`, and `330` must not fire on `3300`.
    """
    for raw in item.get("forbid", []):
        needle = str(raw).lower()
        if not needle:
            continue
        pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
        if re.search(pattern, answer.lower()):
            return str(raw)
    return None


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
    completed = result["status"] == "completed" and result["message_status"] != "abstained"
    # `alt_mention` is the same value written another way ("6400" for the
    # corpus's "6,400"); `mention_all` is the ambiguity-item channel and is
    # handled inside mentions_hit.
    mention_hit = mentions_hit(item, answer)
    cite_hit = any(
        any(book.lower() in doc.lower() for book in item.get("cite", []))
        for doc in _cited_documents(result)
    )
    if not language_ok(item, result):
        return False
    # Checked before the class, so a forbidden value fails an item regardless of
    # what else it got right. A should-abstain item cannot reach here with a
    # forbidden string unless the item is malformed, and then it must fail.
    if forbids_hit(item, answer) is not None:
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
    forbidden = forbids_hit(item, result["answer"])
    if forbidden is not None:
        # Named separately from wrong_class_or_content because the remedy is
        # different: this is the pipeline reaching for a real-world value its
        # own sources contradict, not a retrieval or class problem.
        return f"forbidden_value:{forbidden}"
    expected = item["expect"]
    if expected == "answer" and not result["citations"]:
        return "no_citations"
    return "wrong_class_or_content"


def summarise(
    rows: list[dict[str, Any]], *, served_commit: str | None = None
) -> dict[str, Any]:
    """The run's own counts, in the shape `evals.acceptance_gate` classifies.

    Pure over `rows`, so the numbers a gate reads are testable without a stack.

    The classes are the run's *observed* behaviour, not the item's label:

    - `confident_wrong` — a should-abstain item where the run **asserted an
      answer**: it neither abstained nor said the sources lack it (PRD §5's
      definition, and the scorer's `says_not_in_sources`). A prose "not in the
      sources" reply that carries citations is an *unclean decline*, counted
      against decline accuracy, not here.
    - `clean_decline` — abstained, or plainly said so, **with no citations**.
    - `false_abstention` — an answerable item the run declined on.
    - `uncited_answer` — an answerable item that **did not decline and
      cited nothing**. Every other class above would pass this: it is neither a
      decline, nor an abstention, nor an error, and its text can be perfectly
      correct. It is counted separately precisely because nothing else sees it —
      a content question routed to `chitchat` skips retrieval and answers from
      model memory, and that is the one behaviour this product does not ship.
    - `errored` — the run did not complete. Never a decline: an errored item
      has no behaviour to grade.
    """
    counts = {
        "confident_wrong": 0,
        "clean_declines": 0,
        "unclean_declines": 0,
        "false_abstentions": 0,
        "uncited_answers": 0,
        "errored": 0,
        "answer_items": 0,
        "abstain_items": 0,
        "smalltalk_items": 0,
        "library_items": 0,
        "items": 0,
    }
    detail: dict[str, list[str]] = {
        "confident_wrong_ids": [],
        "clean_decline_ids": [],
        "unclean_decline_ids": [],
        "false_abstention_ids": [],
        "uncited_answer_ids": [],
        "errored_ids": [],
        "failed_ids": [],
    }

    def is_error(row: dict[str, Any]) -> bool:
        return not str(row.get("status") or "").startswith("completed")

    for row in rows:
        counts["items"] += 1
        if not row.get("pass"):
            detail["failed_ids"].append(str(row["id"]))
        errored = is_error(row)
        if errored:
            counts["errored"] += 1
            detail["errored_ids"].append(str(row["id"]))
            continue
        expect = str(row.get("expect"))
        abstained = row.get("message_status") == "abstained"
        cited = bool(row.get("citations"))
        declined = abstained or says_not_in_sources(str(row.get("answer") or ""))
        if expect == "not_in_sources":
            counts["abstain_items"] += 1
            # The order here is PRD §5's, not convenience's. Whether the reply
            # *says the sources lack it* decides confident wrong; citations only
            # split the declines, into clean and unclean. A confident wrong
            # answer normally cites, so checking citations first would file
            # every hallucination as an unclean decline and report zero
            # confident wrong answers — the one number that must never be zero.
            if not declined:
                counts["confident_wrong"] += 1
                detail["confident_wrong_ids"].append(str(row["id"]))
            elif cited:
                # Declined in prose but cited: unclean, per PRD §5. Counted
                # against decline accuracy, not here.
                counts["unclean_declines"] += 1
                detail["unclean_decline_ids"].append(str(row["id"]))
            else:
                counts["clean_declines"] += 1
                detail["clean_decline_ids"].append(str(row["id"]))
        elif expect == "answer":
            counts["answer_items"] += 1
            if declined:
                counts["false_abstentions"] += 1
                detail["false_abstention_ids"].append(str(row["id"]))
            elif not cited:
                # Answered, not declined, and nothing cited. Whether the
                # text is right or wrong is not the question — an answer with no
                # evidence behind it is a different product from this one.
                counts["uncited_answers"] += 1
                detail["uncited_answer_ids"].append(str(row["id"]))
        elif expect == "smalltalk":
            counts["smalltalk_items"] += 1
        elif expect == "library":
            counts["library_items"] += 1

    summary: dict[str, Any] = {"counts": counts}
    if served_commit is not None:
        summary["served_commit"] = served_commit
    return {**summary, "detail": detail, "items": rows}


def write_summary(
    rows: list[dict[str, Any]], path: Path, *, served_commit: str | None = None
) -> dict[str, Any]:
    """Write the summary `evals.acceptance_gate` reads, and return it.

    Sync and called after the run's event loop work is done, so the blocking
    write does not sit inside the async body (`ASYNC240`); the summary is written
    once, at the end, exactly like the raw results file beside it.
    """
    summary = summarise(rows, served_commit=served_commit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))
    return summary


async def served_commit(client: httpx.AsyncClient) -> str:
    """The commit the api this run is talking to is serving.

    Read from the api's own `/healthz`, so it is the code that answered, not a
    commit this script assumes. `unknown` when the api predates the field or is
    unreachable: a run that cannot name what it measured is not a measurement,
    and `evals.acceptance_gate` fails it.
    """
    try:
        response = await client.get("/healthz")
        response.raise_for_status()
        value = response.json().get("served_commit")
    except (httpx.HTTPError, ValueError):
        return "unknown"
    return str(value) if value else "unknown"


async def eval_sign_in(client: httpx.AsyncClient) -> tuple[str, str]:
    """Sign in as the fixed eval account; return (email, password).

    The password comes back out because every turn re-authenticates — the
    access token is a 15-minute TTL and a full run is longer than that.
    """
    email = os.environ.get("EVAL_USER_EMAIL")
    password = os.environ.get("EVAL_USER_PASSWORD")
    if not email or not password:
        raise SystemExit(NO_EVAL_USER)
    response = await client.post("/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise SystemExit(
            f"eval user login failed: {response.status_code} {response.text[:200]}\n"
            "run `make seed-eval-user` to create the account or re-set its password"
        )
    return email, password


async def run(
    only: list[str] | None = None,
    *,
    pace: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    set_file: Path | None = None,
    summary_out: Path | None = None,
) -> None:
    path = set_file or SET_FILE
    dataset = json.loads(path.read_text())
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
    served: str | None = None
    async with httpx.AsyncClient(base_url=smoke_chat.API_URL, timeout=timeout) as client:
        email, password = await eval_sign_in(client)
        print(f"run user {email} (fixed eval account; fresh chat per item)\n")
        # Read once, before the first item, and record it in the summary: the
        # served commit is a property of the process, and a run that measured
        # the wrong checkout has to be able to say so after the fact.
        served = await served_commit(client)
        print(f"api {smoke_chat.API_URL} serving commit {served}\n")

        # **One token, refreshed from its own expiry** — not a login per
        # request. `RATE_LIMIT_LOGIN` is 10 per 60 s per address, and this
        # runner used to log in twice per item (once for the chat, once per
        # turn), so a 57-item run needed ~115 logins and died on item 5 with a
        # 429. That is a harness fault dressed as a product failure: it is
        # `probe_generator_latency.py`'s trap, hit again. The access token is a
        # JWT, not a per-request nonce, so nothing is weakened by reusing it;
        # the only question is when it expires, and the token says so in its own
        # `exp` claim. Refreshed a minute early, because a token that expires
        # mid-run produces a 401 that the turn runner cannot recover from.
        #
        # A token whose `exp` cannot be read falls back to logging in per call:
        # slower, but it cannot be wrong about expiry.
        token_state: dict[str, Any] = {"token": None, "expires_at": 0.0}

        async def fresh_token() -> str:
            now = time.monotonic()
            if token_state["token"] and now < token_state["expires_at"]:
                return str(token_state["token"])
            response = await client.post("/auth/login", json={"email": email, "password": password})
            if response.status_code != 200:
                raise SystemExit(
                    f"eval user login failed mid-run: {response.status_code} {response.text[:200]}"
                )
            token = str(response.json()["access_token"])
            token_state["token"] = token
            token_state["expires_at"] = now + _token_lifetime(token) - TOKEN_REFRESH_MARGIN_SECONDS
            return token

        for item in items:

            async def play(item: dict[str, Any] = item) -> dict[str, Any]:
                token = await fresh_token()
                headers = {"Authorization": f"Bearer {token}"}
                chat = await client.post("/chats", headers=headers, json={"title": None})
                chat_id = str(chat.json()["id"])
                result: dict[str, Any] = {}
                for turn in item["turns"]:
                    fresh = await fresh_token()
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
                    "pending_p2": bool(item.get("pending_p2")),
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
    # `pending_p2` items are the corpus answering a question two ways.
    # They are expected to fail until P2's prompt change, so counting them in
    # today's headline would report a regression that is a known, recorded gap.
    scored = [r for r in rows if not r["pending_p2"]]
    pending = [r for r in rows if r["pending_p2"]]
    per_class: dict[str, list[int]] = {}
    for r in scored:
        per_class.setdefault(r["expect"], []).append(1 if r["pass"] else 0)
    print(
        f"\npassed {sum(r['pass'] for r in scored)}/{len(scored)}; TTFT p50 {p50} ms"
        + (f" ({len(pending)} pending_p2 reported separately)" if pending else "")
    )
    for cls, flags in per_class.items():
        print(f"  {cls}: {sum(flags)}/{len(flags)}")
    per_language: dict[str, list[int]] = {}
    for r in scored:
        per_language.setdefault(str(r["q_language"]), []).append(1 if r["pass"] else 0)
    print("  by question language:")
    for lang, flags in sorted(per_language.items()):
        print(f"    {lang}: {sum(flags)}/{len(flags)}")
    for reason in sorted({r["reason"] for r in scored if r["reason"]}):
        print(f"  failed {reason}: {[r['id'] for r in scored if r['reason'] == reason]}")
    if pending:
        # P2's input, not a defect: what the ambiguity items actually said.
        print("\n  pending P2 (ambiguity items — corpus answers two ways):")
        for r in pending:
            print(
                f"    {r['id']}: {'pass' if r['pass'] else 'FAIL'}"
                f"{' — ' + str(r['reason']) if r['reason'] else ''}"
            )
            print(f"      said: {(r['answer'] or '')[:200]}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}.json"
    out.write_text(json.dumps({"ran_at": stamp, "items": rows}, indent=2))
    print(f"raw results: {out}")

    if summary_out is not None:
        # `--summary-out` rather than scraping the table above: stdout is the
        # operator's log (LiteLLM and Langfuse both write to it), and a verdict
        # read out of a printed table is a verdict read out of a stream — which
        # is how lane B2's probe nearly reported a false failure rate, because
        # a decline streams a delta too. The summary carries the run's own
        # per-item result fields, and `evals.acceptance_gate` classifies from
        # them (`make check-work` step 9).
        write_summary(rows, summary_out, served_commit=served)
        print(f"summary: {summary_out}")


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
    parser.add_argument(
        "--set",
        type=Path,
        default=None,
        help="a different set file (e.g. ../../evals/counterfactual/items.json). "
        "The scorer is shared; only the items and the corpus change.",
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=None,
        help="write this run's counts (confident wrong, clean declines, false "
        "abstentions, errors, and the api's served commit) here, for "
        "`evals.acceptance_gate` to classify. `make check-work` step 9 reads it "
        "from this path rather than scraping stdout.",
    )
    args = parser.parse_args()
    only = args.only.split(",") if args.only else None
    asyncio.run(run(only=only, pace=args.pace, set_file=args.set, summary_out=args.summary_out))
