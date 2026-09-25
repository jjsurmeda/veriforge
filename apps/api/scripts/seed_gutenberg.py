"""Download public-domain books from Project Gutenberg and ingest them as
Shared Library documents.

Uploads go over HTTP to POST /library/documents?shared=true as the admin, so a
book lands in the same object store the workers read from and is queued,
parsed, chunked and embedded by exactly the pipeline a browser upload uses.
sha256 dedupe means a rerun is a no-op.

The texts are not committed: they are cached under .data/gutenberg/ (which is
gitignored) and fetched on demand. Project Gutenberg's licence terms are in
the repo README.

Needs the stack up. Set GUTENBERG_ADMIN_EMAIL and GUTENBERG_ADMIN_PASSWORD.

Usage: `uv run python scripts/seed_gutenberg.py` (or `make seed-books`).
"""

import asyncio
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

CACHE_DIR = Path(os.environ.get("GUTENBERG_CACHE_DIR", ".data/gutenberg"))
BASE_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
API_URL = os.environ.get("VERIFORGE_API_URL", "http://localhost:8000").rstrip("/")
USER_AGENT = "veriforge-seed-gutenberg/1.0 (+local demo corpus)"
POLITE_DELAY_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 1800.0
POLL_SECONDS = 10.0

BOOKS: list[tuple[int, str]] = [
    (1342, "Pride and Prejudice"),
    (1661, "The Adventures of Sherlock Holmes"),
    (84, "Frankenstein"),
    (11, "Alice's Adventures in Wonderland"),
    (35, "The Time Machine"),
]

_MARKER_FLAGS = re.IGNORECASE | re.DOTALL
START_MARKER = re.compile(
    r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", _MARKER_FLAGS
)
END_MARKER = re.compile(
    r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", _MARKER_FLAGS
)


def strip_gutenberg_wrappers(text: str) -> str:
    start = START_MARKER.search(text)
    if start is not None:
        text = text[start.end() :]
    end = END_MARKER.search(text)
    if end is not None:
        text = text[: end.start()]
    return text.strip() + "\n"


def cache_path(book_id: int) -> Path:
    return CACHE_DIR / f"pg{book_id}.txt"


def fetch_book(book_id: int) -> Path:
    path = cache_path(book_id)
    if path.exists() and path.stat().st_size > 0:
        return path
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # S310 on both calls: the URL is built from a hardcoded id, not caller input.
    request = urllib.request.Request(  # noqa: S310
        BASE_URL.format(id=book_id), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        raw = response.read().decode("utf-8", errors="replace")
    path.write_text(strip_gutenberg_wrappers(raw), encoding="utf-8")
    return path


async def sign_in(client: httpx.AsyncClient) -> str:
    email = os.environ.get("GUTENBERG_ADMIN_EMAIL")
    password = os.environ.get("GUTENBERG_ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "set GUTENBERG_ADMIN_EMAIL and GUTENBERG_ADMIN_PASSWORD to the admin "
            "account that should own the Shared library"
        )
    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    if response.status_code != 200:
        raise SystemExit(f"login failed: {response.status_code} {response.text[:200]}")
    return str(response.json()["access_token"])


async def upload_book(
    client: httpx.AsyncClient, token: str, title: str, book_id: int
) -> tuple[str, bool]:
    path = await asyncio.to_thread(fetch_book, book_id)
    data = path.read_bytes()
    response = await client.post(
        "/library/documents",
        params={"shared": "true"},
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (f"{title}.txt", data, "text/plain")},
    )
    if response.status_code != 201:
        raise SystemExit(f"upload failed for {title}: {response.status_code} {response.text[:200]}")
    payload = response.json()
    return str(payload["id"]), bool(payload.get("deduped"))


async def poll_until_ready(client: httpx.AsyncClient, token: str, books: dict[str, str]) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    pending = dict(books)
    while pending and time.monotonic() < deadline:
        for title, document_id in list(pending.items()):
            response = await client.get(f"/documents/{document_id}", headers=headers)
            status = str(response.json()["status"])
            print(f"  {title}: {status}", flush=True)
            if status in {"ready", "failed"}:
                pending.pop(title)
        if pending:
            await asyncio.sleep(POLL_SECONDS)
    if pending:
        print(f"  still ingesting after {int(READY_TIMEOUT_SECONDS)}s: {sorted(pending)}")


async def seed() -> None:
    async with httpx.AsyncClient(base_url=API_URL, timeout=180.0) as client:
        health = await client.get("/healthz")
        if health.status_code != 200:
            raise SystemExit(f"{API_URL} is not answering /healthz — start the stack first")

        token = await sign_in(client)
        print(f"uploading to {API_URL} as {os.environ.get('GUTENBERG_ADMIN_EMAIL')}")

        queued: dict[str, str] = {}
        for index, (book_id, title) in enumerate(BOOKS):
            if index:
                await asyncio.sleep(POLITE_DELAY_SECONDS)
            document_id, deduped = await upload_book(client, token, title, book_id)
            queued[title] = document_id
            state = "already ingested" if deduped else "queued"
            print(f"  {title} ({book_id}) {document_id} {state}")

        await poll_until_ready(client, token, queued)

    print(f"done: {len(queued)} books in the Shared library")


if __name__ == "__main__":
    asyncio.run(seed())
