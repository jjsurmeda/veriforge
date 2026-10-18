"""Ownership scope and client filters for retrieval (TRD §9.2, §11).

The ownership predicate is always injected server-side; client filters are
ANDed *inside* it so they can only narrow, never widen (CLAUDE.md
non-negotiable). Any query touching chunks must go through build_scope —
never construct that predicate inline (python.md).

**One builder, two tables.** `summaries` (TRD §9.1 step 6) is a second copy of
the corpus with its own query, and the failure mode of adding it was going to
be a second, simplified scope predicate written next to this one — which is
how a leak gets in. So `summaries` goes through this function too, with
`ScopeTable.SUMMARIES`, and the differences are stated here rather than
discovered at runtime:

| | `chunks` | `summaries` |
| --- | --- | --- |
| web rows | yes (`c.chat_id`) | **no** — a summary belongs to an uploaded document |
| `source_type` | a real column | implicit: always `document` |
| `page` | a real column | a summary belongs to no single page |
| document branch | yes | yes — **identical predicate**, the only thing shared |

Why no web summaries: step 6 runs in ingest, over uploaded documents. Web
chunks are chat-scoped and expire after seven days (TRD §9.3), so a summary
of one would outlive the thing it summarises.

The document branch is the whole ownership rule and it is written once. The
`page` and `source_type` client filters narrow a summary search to *nothing*
rather than being ignored: a client asking for "page 4" is asking for passages
on page 4, and a summary is not one.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ScopeTable(StrEnum):
    """Which table the scope is being built for. Both carry a document branch
    keyed on the same join, so the ownership rule stays written once."""

    CHUNKS = "chunks"
    SUMMARIES = "summaries"


@dataclass(frozen=True)
class Ownership:
    user_id: UUID
    # The chat's collection ids; re-validated against ownership in SQL.
    collection_ids: Sequence[UUID] = field(default_factory=list)
    # When set, the chat's own web chunks (TRD §9.3) are in scope.
    chat_id: UUID | None = None


@dataclass(frozen=True)
class ClientFilters:
    source_type: str | None = None  # "document" | "web"
    document_ids: Sequence[UUID] | None = None
    tags: Sequence[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    mime: str | None = None
    page: int | None = None


def build_scope(
    ownership: Ownership,
    filters: ClientFilters,
    table: ScopeTable = ScopeTable.CHUNKS,
) -> tuple[str, dict[str, object]]:
    """Return (sql_fragment, params) filtering an aliased `chunks c` table.

    `table` selects which shape to emit; both are aliased `c` and both join
    `documents d` / `collections col`, so the caller writes its query against
    one alias either way. See the module docstring for what differs and why.
    """
    doc_clauses = [
        "d.collection_id = ANY(CAST(:scope_collections AS uuid[]))",
        "(col.owner_id = CAST(:scope_user AS uuid) OR col.visibility = 'shared')",
    ]
    params: dict[str, object] = {
        "scope_collections": [str(c) for c in ownership.collection_ids],
        "scope_user": str(ownership.user_id),
    }
    if filters.document_ids:
        doc_clauses.append("d.id = ANY(CAST(:f_documents AS uuid[]))")
        params["f_documents"] = [str(d) for d in filters.document_ids]
    if filters.tags:
        doc_clauses.append("d.tags ?| CAST(:f_tags AS text[])")
        params["f_tags"] = list(filters.tags)
    if filters.date_from is not None:
        doc_clauses.append("d.created_at >= :f_date_from")
        params["f_date_from"] = filters.date_from
    if filters.date_to is not None:
        doc_clauses.append("d.created_at <= :f_date_to")
        params["f_date_to"] = filters.date_to
    if filters.mime is not None:
        doc_clauses.append("d.mime = :f_mime")
        params["f_mime"] = filters.mime

    # All values enter as bound params; the fragments are code-built constants.
    # `c.source_type = 'document'` only appears on the chunks shape: on
    # summaries the branch IS the document rule and there is no web branch.
    source_clause = (
        "c.source_type = 'document' AND " if table is ScopeTable.CHUNKS else ""
    )
    document_branch = (
        f"({source_clause}c.document_id IN ("  # noqa: S608
        "SELECT d.id FROM documents d JOIN collections col ON col.id = d.collection_id "
        f"WHERE {' AND '.join(doc_clauses)}"
        "))"
    )
    branches = [document_branch]
    if ownership.chat_id is not None and table is ScopeTable.CHUNKS:
        branches.append("(c.source_type = 'web' AND c.chat_id = CAST(:scope_chat AS uuid))")
        params["scope_chat"] = str(ownership.chat_id)

    fragment = "(" + " OR ".join(branches) + ")"
    if filters.source_type is not None:
        if table is ScopeTable.SUMMARIES:
            # A summary is a document summary or nothing. Asking for `web`
            # narrows to nothing, which is what "only web sources" means.
            fragment += " AND FALSE" if filters.source_type == "web" else ""
        else:
            fragment += " AND c.source_type = :f_source_type"
            params["f_source_type"] = filters.source_type
    if filters.page is not None:
        if table is ScopeTable.SUMMARIES:
            # A summary belongs to no single page, so "page N" cannot match one.
            fragment += " AND FALSE"
        else:
            fragment += " AND c.page = :f_page"
            params["f_page"] = filters.page
    return fragment, params
