"""Ownership scope and client filters for retrieval (TRD §9.2, §11).

The ownership predicate is always injected server-side; client filters are
ANDed *inside* it so they can only narrow, never widen (CLAUDE.md
non-negotiable). Any query touching chunks must go through build_scope —
never construct that predicate inline (python.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


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


def build_scope(ownership: Ownership, filters: ClientFilters) -> tuple[str, dict[str, object]]:
    """Return (sql_fragment, params) filtering an aliased `chunks c` table."""
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
    document_branch = (
        "(c.source_type = 'document' AND c.document_id IN ("  # noqa: S608
        "SELECT d.id FROM documents d JOIN collections col ON col.id = d.collection_id "
        f"WHERE {' AND '.join(doc_clauses)}"
        "))"
    )
    branches = [document_branch]
    if ownership.chat_id is not None:
        branches.append("(c.source_type = 'web' AND c.chat_id = CAST(:scope_chat AS uuid))")
        params["scope_chat"] = str(ownership.chat_id)

    fragment = "(" + " OR ".join(branches) + ")"
    if filters.source_type is not None:
        fragment += " AND c.source_type = :f_source_type"
        params["f_source_type"] = filters.source_type
    if filters.page is not None:
        fragment += " AND c.page = :f_page"
        params["f_page"] = filters.page
    return fragment, params
