"""Label audit for the entity-mismatch set (P2a item 0, KI-54).

The label of an entity-mismatch item is the *scope*, not the text: the
question names entity A while only entity B's documents are in scope, so a
clean decline is the only correct answer. That label is proven per item the
D1 way — a zero-hit search for the named entity over **everything the eval
user can retrieve in scope** (the scoped corpus plus every shared collection,
which `resolve_scope` admits to every chat), and the mirror check that the
entity is attested in the *other* corpus, so the item really asks about
something that exists somewhere the pipeline cannot see.

Nothing here compares an item against what the pipeline answered; the
pipeline is not consulted. The scoring core (`audit_entity_items`) is pure,
so it is unit-testable without a database.

Usage:

    uv run python scripts/audit_entity_mismatch.py
    uv run python scripts/audit_entity_mismatch.py --write-back
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ITEMS_FILE = Path(__file__).resolve().parents[3] / "evals" / "entity_mismatch" / "items.json"
SCOPES = ("seed", "counterfactual")


def _normalise(text: str) -> str:
    """Case- and diacritic-folding containment, like audit_labels.normalise."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


@dataclass
class EntityFinding:
    code: str
    detail: str


@dataclass
class EntityAudit:
    item_id: str
    entity: str
    scope: str
    proof: str = ""
    findings: list[EntityFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def audit_entity_items(
    items: Sequence[dict[str, Any]],
    *,
    scoped_chunks: Mapping[str, Sequence[str]],
    shared_chunks: Sequence[str] = (),
) -> list[EntityAudit]:
    """Prove every item's label against the chunk texts it is scored with.

    `scoped_chunks` maps scope name ("seed" / "counterfactual") to the chunk
    texts of that corpus; `shared_chunks` is what `resolve_scope` adds to
    every scope (the shared collections), so the zero-hit proof covers the
    same retrieval scope the runner runs with.
    """
    audits: list[EntityAudit] = []
    for item in items:
        item_id = str(item.get("id") or "?")
        entity = str(item.get("entity") or "")
        scope = str(item.get("scope_corpus") or "")
        audit = EntityAudit(item_id=item_id, entity=entity, scope=scope)
        if not entity:
            audit.findings.append(EntityFinding("no_entity", "item names no entity to prove"))
            audits.append(audit)
            continue
        if scope not in SCOPES:
            audit.findings.append(
                EntityFinding("bad_scope", f"scope_corpus {scope!r} is not one of {SCOPES}")
            )
            audits.append(audit)
            continue
        other = "counterfactual" if scope == "seed" else "seed"
        # Everything the eval user can retrieve for this item: the scoped
        # corpus plus the shared collections resolve_scope admits.
        in_scope = [str(t) for t in scoped_chunks.get(scope, ())] + [str(t) for t in shared_chunks]
        hits_in_scope = [t for t in in_scope if _normalise(entity) in _normalise(t)]
        other_corpus = [str(t) for t in scoped_chunks.get(other, ())]
        hits_other = [t for t in other_corpus if _normalise(entity) in _normalise(t)]

        if hits_in_scope:
            audit.findings.append(
                EntityFinding(
                    "entity_attested_in_scope",
                    f"{entity!r} is attested in {len(hits_in_scope)} chunk(s) of the "
                    f"scoped {scope} corpus — the item would not be a mismatch",
                )
            )
        if not hits_other:
            audit.findings.append(
                EntityFinding(
                    "entity_missing_in_other_corpus",
                    f"{entity!r} is attested nowhere in the {other} corpus — the "
                    "question names an entity that exists in neither corpus",
                )
            )
        if audit.ok:
            audit.proof = (
                f"Zero-hit proof (D1 method): {entity!r} appears in 0 of "
                f"{len(in_scope)} chunk(s) the eval user can retrieve with "
                f"scope_corpus={scope!r} ({len(scoped_chunks.get(scope, ()))} corpus "
                f"chunk(s) + {len(shared_chunks)} shared chunk(s)). Existence check: "
                f"{entity!r} is attested in {len(hits_other)} chunk(s) of the {other} "
                "corpus."
            )
        audits.append(audit)
    return audits


def corpus_chunks_from_db(database_url: str) -> dict[str, list[str]]:
    """Chunk texts per eval corpus, plus every shared collection's chunks
    (the retrieval scope resolve_scope adds on top of the eval corpora)."""
    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _load() -> dict[str, list[str]]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                out: dict[str, list[str]] = {name: [] for name in SCOPES}
                out["shared"] = []
                result = await conn.execute(
                    sa_text(
                        "SELECT col.name, ch.text FROM chunks ch "
                        "JOIN documents d ON d.id = ch.document_id "
                        "JOIN collections col ON col.id = d.collection_id "
                        "WHERE d.status = 'ready' "
                        "AND (col.name IN ('eval-seed-corpus', 'eval-counterfactual-corpus') "
                        "OR col.visibility = 'shared')"
                    )
                )
                for collection_name, chunk_text in result:
                    if collection_name == "eval-seed-corpus":
                        out["seed"].append(str(chunk_text))
                    elif collection_name == "eval-counterfactual-corpus":
                        out["counterfactual"].append(str(chunk_text))
                    else:
                        out["shared"].append(str(chunk_text))
                return out
        finally:
            await engine.dispose()

    return asyncio.run(_load())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=ITEMS_FILE)
    parser.add_argument(
        "--write-back", action="store_true", help="stamp the proofs into items.json"
    )
    args = parser.parse_args()

    payload = json.loads(args.items.read_text(encoding="utf-8"))
    items = payload["items"]
    from config import get_settings

    chunks = corpus_chunks_from_db(get_settings().database_url)
    audits = audit_entity_items(
        items, scoped_chunks=chunks, shared_chunks=chunks["shared"]
    )
    failed = 0
    for audit in audits:
        status = "ok" if audit.ok else "FAIL"
        failed += 0 if audit.ok else 1
        print(f"[{status}] {audit.item_id} ({audit.entity!r}, scope={audit.scope})")
        for finding in audit.findings:
            print(f"    {finding.code}: {finding.detail}")
        if audit.ok:
            print(f"    {audit.proof}")
    if args.write_back:
        by_id = {audit.item_id: audit for audit in audits}
        for item in items:
            match = by_id.get(str(item.get("id")))
            if match is not None and match.ok:
                item["proof"] = match.proof
        args.items.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"proofs written to {args.items}")
    if failed:
        print(f"\n{failed} item(s) fail the audit; fix the item, never the pipeline")
        return 1
    print(f"\n{len(audits)} items audited, all labels proven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
