"""Wire models for the chat-sources and Library endpoints (TRD §12; SR-1,
SR-2, SR-3, SR-4, SR-5)."""

from datetime import datetime

from pydantic import BaseModel, Field


class PageFlag(BaseModel):
    page: int
    flags: list[str]


class DocumentOut(BaseModel):
    id: str
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


class LibraryDocumentOut(DocumentOut):
    shared: bool
    editable: bool


class LibraryOut(BaseModel):
    documents: list[LibraryDocumentOut]
    starter_questions: list[str]


class PinRequest(BaseModel):
    target: str = Field(default="chat", pattern="^(chat|library)$")
