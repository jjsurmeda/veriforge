"""Upload accept path shared by the chat-sources and Library endpoints
(TRD §9.1 step 1, ADR-002).

Dedupe is per container, so the same file uploaded into a chat and into the
Library is embedded twice — see ADR-002's consequences.
"""

import hashlib
from pathlib import PurePath

import filetype
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Collection, Document, User
from errors import AppError
from ingest.storage import document_key, get_object_store
from ingest.tasks import defer_ingest_document
from schemas.sources import DocumentOut

_SNIFFED_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_TEXT_MIMES = {
    ".csv": "text/csv",
    ".html": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


class UploadTooLarge(AppError):
    status_code = 413


class UnsupportedMediaType(AppError):
    status_code = 415


class ReadOnlyAccount(AppError):
    status_code = 403


def deny_read_only(user: User) -> None:
    """The demo role reads Shared documents but never writes (PRD AC-2)."""
    if user.role == "demo":
        raise ReadOnlyAccount("read_only_account", "This account cannot upload documents")


def sniff_upload_mime(filename: str, data: bytes) -> str:
    guessed = filetype.guess(data)
    if guessed is not None:
        if guessed.mime in _SNIFFED_MIMES:
            return str(guessed.mime)
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type")

    mime = _TEXT_MIMES.get(PurePath(filename).suffix.lower())
    if mime is None:
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type") from exc
    return mime


async def read_upload(file: UploadFile) -> tuple[str, bytes]:
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise UploadTooLarge("upload_too_large", "Upload exceeds maximum size")
    return file.filename or "upload", data


def document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=str(document.id),
        name=document.name,
        mime=document.mime,
        sha256=document.sha256,
        status=document.status,
        page_flags=document.page_flags,
        error=document.error,
        tags=document.tags,
        created_at=document.created_at,
    )


async def accept_upload(
    session: AsyncSession, container: Collection, filename: str, data: bytes
) -> tuple[Document, bool]:
    sha256 = hashlib.sha256(data).hexdigest()
    existing = (
        await session.execute(
            select(Document).where(
                Document.collection_id == container.id, Document.sha256 == sha256
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    mime = sniff_upload_mime(filename, data)
    key = document_key(container.id, sha256)
    await get_object_store().put(key, data)
    document = Document(
        collection_id=container.id,
        name=filename,
        mime=mime,
        sha256=sha256,
        s3_key=key,
        status="queued",
        tags=[],
    )
    session.add(document)
    await session.flush()
    await session.commit()
    await defer_ingest_document(document.id)
    return document, False
