"""Wire models for the Sources endpoints (TRD §12; SR-1, SR-2, SR-3, SR-4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CollectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    visibility: str | None = Field(default=None, pattern="^(private|shared)$")


class CollectionOut(BaseModel):
    id: str
    name: str
    visibility: str
    starter_questions: list[str] | None
    document_count: int
    created_at: datetime


class PageFlag(BaseModel):
    page: int
    flags: list[str]


class DocumentOut(BaseModel):
    id: str
    collection_id: str
    name: str
    mime: str
    sha256: str
    status: str
    page_flags: list[PageFlag] | None
    error: str | None
    tags: list[str]
    created_at: datetime


class DocumentUploadOut(DocumentOut):
    deduped: bool = False


class DocumentPatch(BaseModel):
    tags: list[str] = Field(max_length=50)


class ChunkOut(BaseModel):
    id: str
    section_id: str
    ord: int
    page: int | None
    heading_path: str
    text: str
    metadata: dict[str, object] = Field(validation_alias="chunk_metadata")


def collection_out(
    row_id: uuid.UUID,
    name: str,
    visibility: str,
    starter_questions: list[str] | None,
    document_count: int,
    created_at: datetime,
) -> CollectionOut:
    return CollectionOut(
        id=str(row_id),
        name=name,
        visibility=visibility,
        starter_questions=starter_questions,
        document_count=document_count,
        created_at=created_at,
    )
