"""Replay five fixed turns against the seeded corpus and print what happened.

Signs up a normal user, creates one chat with Include Library on (the
default), sends the turns in order, and for each prints the routed intent,
the answer and the citations with their document and page or section. Finishes
with the chat's title, which should be a topic rather than the question.

The turns are chosen to cover the paths that matter: small talk that must not
retrieve, a grounded question that must cite, a question whose scene is not in
this collection and where abstaining is the right answer, a cross-document
comparison, and small talk again at the end.

Usage: `uv run python scripts/smoke_chat.py` (or `make smoke`).
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

API_URL = os.environ.get("VERIFORGE_API_URL", "http://localhost:8000").rstrip("/")
# A throwaway credential: the email is random per run, so this account is abandoned
# the moment the script exits.
PASSWORD = "SmokeChat!234"  # noqa: S105
RUN_TIMEOUT_SECONDS = float(os.environ.get("SMOKE_RUN_TIMEOUT", "240"))

TURNS: list[tuple[str, str]] = [
    ("small talk", "hi there, how's it going?"),
    (
        "grounded",
        "What does Mr. Darcy say in his first proposal to Elizabeth, and how does she answer?",
    ),
    (
        "abstain",
        "How does Sherlock Holmes figure out Watson had been in Afghanistan?",
    ),
    (
        "cross-document",
        "Compare how Victor Frankenstein and the Time Traveller deal with the "
        "consequences of their inventions.",
    ),
    ("small talk", "thanks!"),
]


async def sign_up(client: httpx.AsyncClient) -> str:
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    response = await client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    if response.status_code != 201:
        raise SystemExit(f"signup failed: {response.status_code} {response.text[:200]}")
    return email


async def sign_in(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    if response.status_code != 200:
        raise SystemExit(f"login failed: {response.status_code} {response.text[:200]}")
    return str(response.json()["access_token"])


async def run_turn(
    client: httpx.AsyncClient, token: str, chat_id: str, message: str
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        f"/chats/{chat_id}/runs",
        headers=headers,
        json={"message": message, "mode": "auto", "source": "upload"},
    )
    if created.status_code != 201:
        raise SystemExit(f"run failed: {created.status_code} {created.text[:200]}")
    run_id = created.json()["run_id"]

    intent = "unknown"
    steps: list[str] = []
    answer = ""
    status = "timeout"
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS

    async def read_events() -> None:
        nonlocal intent, answer, status
        async with client.stream(
            "GET", f"/runs/{run_id}/stream", headers=headers, params={"after_seq": 0}
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                kind = event.get("type")
                if kind == "decision" and event.get("name") == "intent":
                    intent = str(event.get("value"))
                elif kind == "step.started":
                    steps.append(str(event.get("label")))
                elif kind == "answer.delta":
                    answer += str(event.get("text", ""))
                elif kind == "run.completed":
                    status = "completed"
                    break
                elif kind == "run.failed":
                    status = f"failed ({event.get('error_code')})"
                    break
                elif kind == "run.cancelled":
                    status = "cancelled"
                    break

    try:
        await asyncio.wait_for(read_events(), timeout=max(1.0, deadline - time.monotonic()))
    except TimeoutError:
        status = "timeout"
    except httpx.HTTPError as error:
        status = f"stream dropped ({type(error).__name__})"

    assistant: list[dict[str, Any]] = []
    try:
        response = await client.get(f"/chats/{chat_id}/messages", headers=headers)
        payload = response.json()
        if isinstance(payload, list):
            assistant = [
                m for m in payload if m["role"] == "assistant" and m.get("run_id") == run_id
            ]
        else:
            status = f"messages unavailable ({response.status_code})"
    except httpx.HTTPError as error:
        status = f"messages unavailable ({type(error).__name__})"
    citations: list[str] = []
    if assistant:
        for citation in assistant[-1].get("citations") or []:
            document = citation.get("document_name") or citation.get("document_id") or "?"
            where = citation.get("page")
            section = citation.get("section_id")
            locator = (
                f" p.{where}" if where is not None else (f" §{section[:8]}" if section else "")
            )
            citations.append(f"[{citation.get('n')}] {document}{locator}")
    if answer and assistant and not assistant[-1].get("content"):
        answer = str(assistant[-1]["content"])
    return {
        "intent": intent,
        "status": status,
        "answer": answer.strip(),
        "citations": citations,
        "steps": steps,
    }


async def main() -> None:
    timeout = httpx.Timeout(connect=30.0, read=RUN_TIMEOUT_SECONDS, write=60.0, pool=60.0)
    async with httpx.AsyncClient(base_url=API_URL, timeout=timeout) as client:
        email = await sign_up(client)
        token = await sign_in(client, email)
        chat = (
            await client.post(
                "/chats", headers={"Authorization": f"Bearer {token}"}, json={"title": None}
            )
        ).json()
        chat_id = str(chat["id"])
        print(f"chat {chat_id} as {email} (Include Library on by default)\n")

        for label, message in TURNS:
            # Access tokens are short-lived and a slow provider can push the
            # whole script past their lifetime, so take a fresh one per turn.
            token = await sign_in(client, email)
            print("=" * 72)
            print(f"[{label}] {message}")
            result = await run_turn(client, token, chat_id, message)
            print(f"  intent    : {result['intent']}")
            print(f"  status    : {result['status']}")
            print(f"  steps     : {', '.join(str(s) for s in result['steps']) or '-'}")
            answer = str(result["answer"])
            print(f"  answer    : {answer[:400]}{'…' if len(answer) > 400 else ''}")
            citations = list(result["citations"])
            if citations:
                print("  citations :")
                for citation in citations:
                    print(f"              {citation}")
            else:
                print("  citations : (none)")
            print()

        title = (
            await client.get(f"/chats/{chat_id}", headers={"Authorization": f"Bearer {token}"})
        ).json()["title"]
        print("=" * 72)
        print(f"final title: {title!r}")


if __name__ == "__main__":
    asyncio.run(main())
