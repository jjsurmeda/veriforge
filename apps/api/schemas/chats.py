import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None
    model_id: str | None = Field(default=None, max_length=128)


class ChatOut(BaseModel):
    id: str
    title: str
    pinned: bool
    model_id: str | None
    created_at: datetime
    active_run_id: str | None = None


class CitationOut(BaseModel):
    n: int
    chunk_id: str | None = None
    document_id: str | None = None
    document_name: str | None = None
    page: int | None = None
    excerpt: str | None = None
    rerank_score: float | None = None
    # Reviewer fields — null until slice 6 (TRD §10).
    verdict: str | None = None
    p_supported: float | None = None


class MessageOut(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    status: str | None
    created_at: datetime
    citations: list[CitationOut] = []


class RunFilters(BaseModel):
    """Client filters on a run (TRD §12); every field can only narrow the
    server-side ownership scope (TRD §9.2)."""

    source_type: str | None = Field(default=None, pattern="^(document|web)$")
    document_ids: list[uuid.UUID] | None = None
    tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    mime: str | None = None
    page: int | None = Field(default=None, ge=1)


class RunCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    model_id: str | None = Field(default=None, max_length=128)
    mode: str = Field(default="fast", pattern="^(fast|auto|deep)$")
    source: str = Field(default="auto", pattern="^(auto|upload|web|both)$")
    collection_ids: list[uuid.UUID] | None = None
    filters: RunFilters | None = None


class RunCreateResponse(BaseModel):
    run_id: str
    message_id: str


class RunCancelResponse(BaseModel):
    run_id: str
    status: str


def chat_out(
    row_id: uuid.UUID,
    title: str,
    pinned: bool,
    model_id: str | None,
    created_at: datetime,
    active_run_id: uuid.UUID | None,
) -> ChatOut:
    return ChatOut(
        id=str(row_id),
        title=title,
        pinned=pinned,
        model_id=model_id,
        created_at=created_at,
        active_run_id=str(active_run_id) if active_run_id else None,
    )


def message_out(
    row_id: uuid.UUID,
    chat_id: uuid.UUID,
    role: str,
    content: str,
    status: str | None,
    created_at: datetime,
    citations: list[CitationOut] | None = None,
) -> MessageOut:
    return MessageOut(
        id=str(row_id),
        chat_id=str(chat_id),
        role=role,
        content=content,
        status=status,
        created_at=created_at,
        citations=citations or [],
    )
