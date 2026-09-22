"""Run stream (SSE, resumable via ?after_seq=) and cancel (TRD §12)."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.models import Chat, Message, Run, User
from db.session import get_session
from errors import AppError
from schemas.chats import RunCancelResponse
from schemas.events import RunStreamResponse

router = APIRouter(prefix="/runs", tags=["runs"])


class RunNotFound(AppError):
    status_code = 404


async def _owned_run(
    session: AsyncSession, user: User, run_id: UUID
) -> tuple[Run, Message, Chat]:
    row = (
        await session.execute(
            select(Run, Message, Chat)
            .join(Message, Run.message_id == Message.id)
            .join(Chat, Message.chat_id == Chat.id)
            .where(Run.id == run_id, Chat.user_id == user.id)
        )
    ).first()
    if row is None:
        raise RunNotFound("run_not_found", "Run not found")
    run, message, chat = row
    return run, message, chat


@router.get(
    "/{run_id}/stream",
    responses={200: {"model": RunStreamResponse, "description": "SSE event stream"}},
)
async def stream_run(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    await _owned_run(session, user, run_id)
    bus = request.app.state.bus

    async def event_stream() -> AsyncIterator[str]:
        async for event in bus.subscribe(run_id, after_seq):
            data = event.model_dump_json()
            yield f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/cancel", response_model=RunCancelResponse)
async def cancel_run(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunCancelResponse:
    run, _, _ = await _owned_run(session, user, run_id)
    if run.status == "running":
        await request.app.state.bus.cancel(run_id)
    return RunCancelResponse(run_id=str(run.id), status=run.status)
