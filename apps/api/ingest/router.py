"""Library and document routes (TRD §12; SR-1, SR-2, SR-3, SR-4, ADR-002).

`collections` rows are internal containers: the Library flattens the user's
own and the Shared ones into one list, and a chat's own sources are served
from the chats router. Ownership is checked on every document.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from chats.scope import library_starter_questions
from db.models import Document, User
from db.session import get_session
from errors import AppError
from ingest.containers import get_or_create_shared_collection
from ingest.repository import (
    get_owned_document,
    get_visible_document,
    list_document_chunks,
    list_shared_documents,
)
from ingest.storage import get_object_store
from ingest.tasks import defer_ingest_document
from ingest.upload import accept_upload, deny_read_only, document_out, read_upload
from schemas.sources import (
    ChunkOut,
    DocumentOut,
    DocumentPatch,
    DocumentUploadOut,
    LibraryDocumentOut,
    LibraryOut,
)

router = APIRouter(tags=["library"])
logger = logging.getLogger(__name__)


class DocumentNotFound(AppError):
    status_code = 404


class Forbidden(AppError):
    status_code = 403


def upload_out(document: Document, deduped: bool) -> DocumentUploadOut:
    return DocumentUploadOut(**document_out(document).model_dump(), deduped=deduped)


async def _owned_document_or_404(
    session: AsyncSession, user: User, document_id: UUID
) -> Document:
    document = await get_owned_document(session, user, document_id)
    if document is None:
        raise DocumentNotFound("document_not_found", "Document not found")
    return document


@router.get("/library", response_model=LibraryOut)
async def get_library(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LibraryOut:
    documents = await list_shared_documents(session)
    return LibraryOut(
        documents=[
            LibraryDocumentOut(
                **document_out(document).model_dump(), shared=True, editable=user.role == "admin"
            )
            for document in documents
        ],
        starter_questions=await library_starter_questions(session),
    )


@router.post("/library/documents", response_model=DocumentUploadOut, status_code=201)
async def upload_library_document(
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentUploadOut:
    deny_read_only(user)
    if user.role != "admin":
        raise Forbidden("forbidden", "Only admins can publish to the Shared library")
    container = await get_or_create_shared_collection(session, user)
    filename, data = await read_upload(file)
    document, deduped = await accept_upload(session, container, filename, data)
    return upload_out(document, deduped)


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
