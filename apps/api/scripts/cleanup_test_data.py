"""One-off test-data cleanup (owner-approved delete, prompt 2026-09-30-0008).

Deletes:
  (a) documents in kind='library' AND visibility='private' collections whose
      owner is not one of KEPT_EMAILS (stale duplicate test uploads, out of
      retrieval scope since the ADR-002 addendum);
  (b) every chat owned by any other account — chat collections, documents,
      messages and runs go via the DB's ON DELETE CASCADE.

Never deletes: any user row, any shared collection or its documents, anything
owned by KEPT_EMAILS.

Dry run by default; pass --apply to execute. Object-store files for the
deleted documents are removed afterwards via the same path the document
DELETE route uses (get_object_store().delete).

Usage (inside the api container, so OBJECT_STORAGE_DIR=/data/objects):
  uv run python scripts/cleanup_test_data.py           # dry run
  uv run python scripts/cleanup_test_data.py --apply
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import get_settings
from ingest.storage import get_object_store

KEPT_EMAILS = ("jjsurmeda@gmail.com", "booksadmin@example.com", "evals@veriforge.local")


def _q(sql: str, *expand: str) -> Any:
    return text(sql).bindparams(*[bindparam(name, expanding=True) for name in expand])

SELECT_A = """
SELECT d.id::text AS id, d.name, d.s3_key, u.email
FROM documents d
JOIN collections c ON c.id = d.collection_id
JOIN users u ON u.id = c.owner_id
WHERE c.kind = 'library' AND c.visibility = 'private'
  AND u.email NOT IN :kept
ORDER BY u.email, d.name
"""

SELECT_B_CHATS = """
SELECT ch.id::text AS id, u.email
FROM chats ch JOIN users u ON u.id = ch.user_id
WHERE u.email NOT IN :kept
ORDER BY u.email
"""

SELECT_B_KEYS = """
SELECT DISTINCT d.s3_key FROM documents d
WHERE d.collection_id IN (SELECT id FROM collections WHERE chat_id IN :chat_ids)
"""

SHARED_COUNT = """
SELECT count(*) FROM documents d
JOIN collections c ON c.id = d.collection_id
WHERE c.visibility = 'shared'
"""

CHAT_COUNT = "SELECT count(*) FROM chats"
DOC_COUNT = "SELECT count(*) FROM documents"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        a_rows = (
            (await session.execute(_q(SELECT_A, "kept"), {"kept": KEPT_EMAILS})).mappings().all()
        )
        b_rows = (
            (await session.execute(_q(SELECT_B_CHATS, "kept"), {"kept": KEPT_EMAILS}))
            .mappings()
            .all()
        )
        chat_ids = [r["id"] for r in b_rows]
        b_keys: list[str] = []
        if chat_ids:
            b_keys = [
                r[0]
                for r in (
                    await session.execute(
                        _q(SELECT_B_KEYS, "chat_ids"), {"chat_ids": tuple(chat_ids)}
                    )
                ).all()
            ]

        a_keys = [r["s3_key"] for r in a_rows]
        b_emails = sorted({r["email"] for r in b_rows})
        a_by_email: dict[str, int] = {}
        for r in a_rows:
            a_by_email[r["email"]] = a_by_email.get(r["email"], 0) + 1

        print(f"KEPT accounts: {', '.join(KEPT_EMAILS)}")
        print(f"(a) private-library documents to delete: {len(a_rows)}")
        for email, n in sorted(a_by_email.items()):
            print(f"    {email}: {n}")
        print(f"(b) chats to delete: {len(b_rows)} across {len(b_emails)} accounts")
        for email in b_emails:
            print(f"    {email}")
        leaked = [e for e in KEPT_EMAILS if e in b_emails or e in a_by_email]
        if leaked:
            print(f"ABORT: kept account in delete set: {leaked}")
            sys.exit(1)
        print("kept accounts are NOT in the delete set")

        docs_before = (await session.execute(text(DOC_COUNT))).scalar_one()
        chats_before = (await session.execute(text(CHAT_COUNT))).scalar_one()
        shared_before = (await session.execute(text(SHARED_COUNT))).scalar_one()
        print(f"before: documents={docs_before} chats={chats_before} shared_docs={shared_before}")

        if not args.apply:
            print("dry run; pass --apply to delete")
            await engine.dispose()
            return

        await session.rollback()
        async with session.begin():
            if a_rows:
                await session.execute(
                    _q("DELETE FROM documents WHERE id IN :ids", "ids"),
                    {"ids": tuple(r["id"] for r in a_rows)},
                )
            if chat_ids:
                await session.execute(
                    _q("DELETE FROM chats WHERE id IN :ids", "ids"), {"ids": tuple(chat_ids)}
                )

        docs_after = (await session.execute(text(DOC_COUNT))).scalar_one()
        chats_after = (await session.execute(text(CHAT_COUNT))).scalar_one()
        shared_after = (await session.execute(text(SHARED_COUNT))).scalar_one()
        print(f"after:  documents={docs_after} chats={chats_after} shared_docs={shared_after}")
        if shared_after != shared_before:
            print("ABORT: shared document count changed")
            sys.exit(1)

    store = get_object_store()
    removed = 0
    for key in dict.fromkeys(a_keys + b_keys):
        try:
            await store.delete(key)
            removed += 1
        except OSError:
            print(f"object delete failed (continuing): {key}")
    print(f"object-store files removed: {removed} of {len(set(a_keys + b_keys))}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
