"""Dump gold chunk ids (answer_passages.json) and a passage-digest -> chunk id
map from the database, so the shadow analysis replays offline.

    DATABASE_URL=... python -m scripts.shadow_gold <out-dir>
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from db.session import get_session_factory
from retrieval.rerank import _PASSAGE_CHARS
from scripts.measure_recall import LABELS, _gold


async def main(out: Path) -> None:
    labels = json.loads(LABELS.read_text())["items"]
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    async with get_session_factory()() as session:
        gold = {iid: sorted(await _gold(session, label)) for iid, label in labels.items()}
        rows = await session.execute(
            text(
                "select c.id, c.text, d.name from chunks c join documents d on d.id = c.document_id"
            )
        )
        digest: dict[str, list[str]] = {}
        docs: dict[str, str] = {}
        for cid, body, name in rows:
            key = hashlib.sha1(body[:_PASSAGE_CHARS].encode(), usedforsecurity=False).hexdigest()[
                :12
            ]
            digest.setdefault(key, []).append(str(cid))
            docs[str(cid)] = name
    (out / "gold.json").write_text(json.dumps(gold))
    (out / "chunkmap.json").write_text(json.dumps({"digest": digest, "doc": docs}))
    print(f"gold items {len(gold)}, chunks {len(docs)}, digests {len(digest)}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
