"""Chat CRUD, messages, run creation (TRD §12). Ownership filters are
injected server-side on every query (CLAUDE.md non-negotiable)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import CurrentUser
from db.models import Chat, LlmProvider, Message, Model, ModelRole, Run, User
from db.session import get_session
from errors import AppError
from graph import runner
from schemas.chats import (
    ChatCreate,
    ChatOut,
    ChatPatch,
    MessageOut,
    RunCreateRequest,
    RunCreateResponse,
    chat_out,
    message_out,
)

router = APIRouter(tags=["chats"])


class ChatNotFound(AppError):
    status_code = 404


class ModelNotAvailable(AppError):
    status_code = 422


async def _owned_chat(session: AsyncSession, user: User, chat_id: UUID) -> Chat:
    chat = (
        await session.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    ).scalar_one_or_none()
    if chat is None:
        raise ChatNotFound("chat_not_found", "Chat not found")
    return chat


async def _default_model_id(session: AsyncSession) -> str:
    role = (
        await session.execute(select(ModelRole).where(ModelRole.role == "generator"))
    ).scalar_one_or_none()
    if role is not None:
        return role.model_id
    first = (
        (await session.execute(select(Model).where(Model.enabled).order_by(Model.model_id)))
        .scalars()
        .first()
    )
    if first is None:
        raise AppError("no_models", "No models are configured", status_code=500)
    return first.model_id


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChatOut]:
    active_run = (
        select(Run.id)
        .join(Message, Run.message_id == Message.id)
        .where(Message.chat_id == Chat.id, Run.status == "running")
        .order_by(Run.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(Chat, active_run)
            .where(Chat.user_id == user.id)
            .order_by(Chat.created_at.desc())
        )
    ).all()
    return [
        chat_out(
            chat.id, chat.title, chat.pinned, chat.model_id, chat.created_at, active
        )
        for chat, active in rows
    ]


@router.post("/chats", response_model=ChatOut, status_code=201)
async def create_chat(
    body: ChatCreate,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatOut:
    chat = Chat(
        user_id=user.id,
        title=body.title or "New chat",
        model_id=await _default_model_id(session),
    )
    session.add(chat)
    await session.flush()
    return chat_out(chat.id, chat.title, chat.pinned, chat.model_id, chat.created_at, None)


@router.get("/chats/{chat_id}", response_model=ChatOut)
async def get_chat(
    chat_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatOut:
    chat = await _owned_chat(session, user, chat_id)
    active_run = (
        await session.execute(
            select(Run.id)
            .join(Message, Run.message_id == Message.id)
            .where(Message.chat_id == chat.id, Run.status == "running")
            .order_by(Run.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return chat_out(chat.id, chat.title, chat.pinned, chat.model_id, chat.created_at, active_run)


@router.patch("/chats/{chat_id}", response_model=ChatOut)
async def patch_chat(
    chat_id: UUID,
    body: ChatPatch,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatOut:
    chat = await _owned_chat(session, user, chat_id)
    if body.title is not None:
        chat.title = body.title
    if body.pinned is not None:
        chat.pinned = body.pinned
    if body.model_id is not None:
        await _assert_model_available(session, body.model_id)
        chat.model_id = body.model_id
    await session.flush()
    return chat_out(chat.id, chat.title, chat.pinned, chat.model_id, chat.created_at, None)


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    chat = await _owned_chat(session, user, chat_id)
    await session.delete(chat)


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
async def list_messages(
    chat_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MessageOut]:
    await _owned_chat(session, user, chat_id)
    messages = (
        await session.execute(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        )
    ).scalars().all()
    return [
        message_out(m.id, m.chat_id, m.role, m.content, m.status, m.created_at) for m in messages
    ]


async def _assert_model_available(
    session: AsyncSession, model_id: str
) -> tuple[Model, LlmProvider]:
    row = (
        await session.execute(
            select(Model, LlmProvider)
            .join(LlmProvider, Model.provider_id == LlmProvider.id)
            .where(Model.model_id == model_id, Model.enabled, LlmProvider.enabled)
        )
    ).first()
    if row is None:
        raise ModelNotAvailable("model_not_available", f"Model {model_id} is not enabled")
    model, provider = row
    return model, provider


@router.post("/chats/{chat_id}/runs", response_model=RunCreateResponse, status_code=201)
async def create_run(
    chat_id: UUID,
    body: RunCreateRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunCreateResponse:
    chat = await _owned_chat(session, user, chat_id)
    model_id = body.model_id or chat.model_id
    if model_id is None:
        model_id = await _default_model_id(session)
    _, provider = await _assert_model_available(session, model_id)

    user_message = Message(chat_id=chat.id, role="user", content=body.message, status="complete")
    assistant_message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    session.add(user_message)
    session.add(assistant_message)
    await session.flush()

    run = Run(
        message_id=assistant_message.id,
        mode=body.mode,
        source="auto",
        model_id=model_id,
        status="running",
        heartbeat_at=None,
    )
    session.add(run)
    await session.commit()

    runner.start_run(
        bus=request.app.state.bus,
        session_factory=request.app.state.session_factory,
        run_id=run.id,
        message_id=assistant_message.id,
        chat_id=chat.id,
        user_id=user.id,
        litellm_model=f"{provider.kind}/{model_id}",
        model_id=model_id,
        mode=body.mode,
        source="auto",
        user_message=body.message,
    )
    return RunCreateResponse(run_id=str(run.id), message_id=str(assistant_message.id))
