import hashlib
import logging
from pathlib import PurePath
from typing import Annotated
from uuid import UUID

import filetype
from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from config import get_settings
from db.models import Collection, Document, User
from db.session import get_session
from errors import AppError
from ingest.repository import (
    get_owned_collection,
    get_owned_document,
    get_visible_collection,
    get_visible_document,
    list_collection_documents,
    list_document_chunks,
    visible_collections,
)
from ingest.storage import document_key, get_object_store
from ingest.tasks import defer_ingest_document
from schemas.sources import (
    ChunkOut,
    CollectionCreate,
    CollectionOut,
    CollectionPatch,
    DocumentOut,
    DocumentPatch,
    DocumentUploadOut,
    collection_out,
)

router = APIRouter(tags=["sources"])
logger = logging.getLogger(__name__)

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


class CollectionNotFound(AppError):
    status_code = 404


class DocumentNotFound(AppError):
    status_code = 404


class UploadTooLarge(AppError):
    status_code = 413


class UnsupportedMediaType(AppError):
    status_code = 415


class Forbidden(AppError):
    status_code = 403


def document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=str(document.id),
        collection_id=str(document.collection_id),
        name=document.name,
        mime=document.mime,
        sha256=document.sha256,
        status=document.status,
        page_flags=document.page_flags,
        error=document.error,
        tags=document.tags,
        created_at=document.created_at,
    )


def _upload_out(document: Document, *, deduped: bool) -> DocumentUploadOut:
    return DocumentUploadOut(**document_out(document).model_dump(), deduped=deduped)


async def _owned_collection_or_404(
    session: AsyncSession, user: User, collection_id: UUID
) -> Collection:
    collection = await get_owned_collection(session, user, collection_id)
    if collection is None:
        raise CollectionNotFound("collection_not_found", "Collection not found")
    return collection


async def _owned_document_or_404(session: AsyncSession, user: User, document_id: UUID) -> Document:
    document = await get_owned_document(session, user, document_id)
    if document is None:
        raise DocumentNotFound("document_not_found", "Document not found")
    return document


def _sniff_mime(filename: str, data: bytes) -> str:
    guessed = filetype.guess(data)
    if guessed is not None:
        if guessed.mime in _SNIFFED_MIMES:
            return str(guessed.mime)
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type")

    suffix = PurePath(filename).suffix.lower()
    mime = _TEXT_MIMES.get(suffix)
    if mime is None:
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedMediaType("unsupported_media_type", "Unsupported media type") from exc
    return mime


async def _multipart_file(file: UploadFile) -> tuple[str, bytes]:
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise UploadTooLarge("upload_too_large", "Upload exceeds maximum size")
    return file.filename or "upload", data


@router.get("/collections", response_model=list[CollectionOut])
async def list_collections(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CollectionOut]:
    rows = await visible_collections(session, user)
    return [
        collection_out(
            collection.id,
            collection.name,
            collection.visibility,
            collection.starter_questions,
            count,
            collection.created_at,
        )
        for collection, count in rows
    ]


@router.post("/collections", response_model=CollectionOut, status_code=201)
async def create_collection(
    body: CollectionCreate,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CollectionOut:
    collection = Collection(owner_id=user.id, name=body.name, visibility="private")
    session.add(collection)
    await session.flush()
    return collection_out(
        collection.id,
        collection.name,
        collection.visibility,
        collection.starter_questions,
        0,
        collection.created_at,
    )


@router.get("/collections/{collection_id}", response_model=CollectionOut)
async def get_collection(
    collection_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CollectionOut:
    collection = await get_visible_collection(session, user, collection_id)
    if collection is None:
        raise CollectionNotFound("collection_not_found", "Collection not found")
    doc_count = (
        await session.execute(select(Document.id).where(Document.collection_id == collection.id))
    ).all()
    return collection_out(
        collection.id,
        collection.name,
        collection.visibility,
        collection.starter_questions,
        len(doc_count),
        collection.created_at,
    )


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def patch_collection(
    collection_id: UUID,
    body: CollectionPatch,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CollectionOut:
    collection = await _owned_collection_or_404(session, user, collection_id)
    if body.visibility == "shared" and user.role != "admin":
        raise Forbidden("forbidden", "Only admins can publish shared collections")
    if body.name is not None:
        collection.name = body.name
    if body.visibility is not None:
        collection.visibility = body.visibility
    await session.flush()
    doc_count = (
        await session.execute(select(Document.id).where(Document.collection_id == collection.id))
    ).all()
    return collection_out(
        collection.id,
        collection.name,
        collection.visibility,
        collection.starter_questions,
        len(doc_count),
        collection.created_at,
    )


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    collection = await _owned_collection_or_404(session, user, collection_id)
    await session.delete(collection)


@router.post(
    "/collections/{collection_id}/documents",
    response_model=DocumentUploadOut,
    status_code=201,
)
async def upload_document(
    collection_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentUploadOut:
    collection = await _owned_collection_or_404(session, user, collection_id)
    filename, data = await _multipart_file(file)

    sha256 = hashlib.sha256(data).hexdigest()
    existing = (
        await session.execute(
            select(Document).where(
                Document.collection_id == collection.id, Document.sha256 == sha256
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _upload_out(existing, deduped=True)

    mime = _sniff_mime(filename, data)
    key = document_key(collection.id, sha256)
    await get_object_store().put(key, data)
    document = Document(
        collection_id=collection.id,
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
    return _upload_out(document, deduped=False)


@router.get("/collections/{collection_id}/documents", response_model=list[DocumentOut])
async def get_collection_documents(
    collection_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentOut]:
    documents = await list_collection_documents(session, user, collection_id)
    if documents is None:
        raise CollectionNotFound("collection_not_found", "Collection not found")
    return [document_out(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentOut:
    document = await get_visible_document(session, user, document_id)
    if document is None:
        raise DocumentNotFound("document_not_found", "Document not found")
    return document_out(document)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def patch_document(
    document_id: UUID,
    body: DocumentPatch,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentOut:
    document = await _owned_document_or_404(session, user, document_id)
    document.tags = body.tags
    await session.flush()
    return document_out(document)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    document = await _owned_document_or_404(session, user, document_id)
    key = document.s3_key
    await session.delete(document)
    await session.commit()
    try:
        await get_object_store().delete(key)
    except OSError:
        logger.warning("failed to delete object %s", key, exc_info=True)


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentOut:
    document = await _owned_document_or_404(session, user, document_id)
    document.status = "queued"
    document.error = None
    await session.flush()
    await session.commit()
    await defer_ingest_document(document.id)
    return document_out(document)


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def get_document_chunks(
    document_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChunkOut]:
    rows = await list_document_chunks(session, user, document_id)
    if rows is None:
        raise DocumentNotFound("document_not_found", "Document not found")
    return [
        ChunkOut(
            id=str(chunk.id),
            section_id=str(section.id),
            ord=chunk.ord,
            page=chunk.page,
            heading_path=section.heading_path,
            text=chunk.text,
            chunk_metadata=chunk.chunk_metadata,
        )
        for chunk, section in rows
    ]
