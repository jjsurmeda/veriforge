"""Web-source routes (TRD §12): pin a fetched web page into a collection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.session import get_session
from retrieval.web import pin_web_page

router = APIRouter(tags=["web-sources"])


class PinRequest(BaseModel):
    collection_id: UUID


class PinResponse(BaseModel):
    document_id: str


@router.post("/web-sources/{web_page_id}/pin", response_model=PinResponse, status_code=201)
async def pin_web_source(
    web_page_id: UUID,
    body: PinRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PinResponse:
    document = await pin_web_page(
        session, user_id=user.id, web_page_id=web_page_id, collection_id=body.collection_id
    )
    return PinResponse(document_id=str(document.id))
