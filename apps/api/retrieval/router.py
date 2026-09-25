"""Web-source routes (TRD §12, SR-5): pin a fetched web page into a chat's
own sources or the user's Library."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.models import Chat, WebPage
from db.session import get_session
from errors import AppError
from ingest.containers import get_or_create_chat_collection, get_or_create_library_collection
from ingest.upload import deny_read_only
from retrieval.web import pin_web_page
from schemas.sources import PinRequest

router = APIRouter(tags=["web-sources"])


class PinResponse(BaseModel):
    document_id: str


@router.post("/web-sources/{web_page_id}/pin", response_model=PinResponse, status_code=201)
async def pin_web_source(
    web_page_id: UUID,
    body: PinRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PinResponse:
    deny_read_only(user)
    page = await session.get(WebPage, web_page_id)
    if page is None:
        raise AppError("web_source_not_found", "Web source not found", status_code=404)
    if body.target == "chat":
        chat = await session.get(Chat, page.chat_id)
        if chat is None or chat.user_id != user.id:
            raise AppError("web_source_not_found", "Web source not found", status_code=404)
        container = await get_or_create_chat_collection(session, user, chat)
    else:
        container = await get_or_create_library_collection(session, user)
    document = await pin_web_page(
        session, user_id=user.id, web_page_id=web_page_id, collection_id=container.id
    )
    return PinResponse(document_id=str(document.id))
