"""SQLAlchemy models for TRD §13's tables.

Slice 1 subset: auth, chats, messages, runs, run_events and the model
catalogue. Pydantic wire models live in schemas/ and are never imported
from here (docs/conventions/python.md: Pydantic and SQLAlchemy, never
conflated).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from db.ids import uuid7

userrole = Enum("user", "admin", "demo", name="userrole", create_type=True)
messagerole = Enum("user", "assistant", name="messagerole", create_type=True)
messagestatus = Enum(
    "complete", "cancelled", "abstained", "failed", name="messagestatus", create_type=True
)
runstatus = Enum("running", "completed", "cancelled", "failed", name="runstatus", create_type=True)
runmode = Enum("fast", "auto", "deep", name="runmode", create_type=True)
runsource = Enum("auto", "web", "collections", name="runsource", create_type=True)


class Base(DeclarativeBase):
    pass


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    credits_5h: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_month: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # Null for OAuth-only accounts.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(userrole, nullable=False, default="user")
    # Live FK now; the quota gate that reads it arrives in slice 7 (TRD §17).
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OauthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the raw token; the raw value never lands in the database.
    hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Catalogue model id (e.g. "openai/gpt-4o-mini"), not an FK: catalogue
    # rows are managed by admin (slice 7) and chats must survive catalogue
    # changes.
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    collection_ids: Mapped[list[uuid.UUID] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_created", "chat_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(messagerole, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Null while the assistant message is still streaming (TRD §13 status
    # values only cover terminal states).
    status: Mapped[str | None] = mapped_column(messagestatus, nullable=True)
    revised_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_runs_message", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    # The assistant message this run produces (created up front, content
    # lands at finalisation).
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(runmode, nullable=False, default="fast")
    source: Mapped[str] = mapped_column(runsource, nullable=False, default="auto")
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    settings_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # status/heartbeat_at are not in TRD §13's column list but the §7 sweep
    # ("60 s without heartbeat is marked failed") needs them.
    status: Mapped[str] = mapped_column(runstatus, nullable=False, default="running")
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="openrouter")
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Encrypted at rest from slice 7 (TRD §11 Fernet); slice 1 uses the
    # OPENROUTER_API_KEY env var.
    api_key_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Model(Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    price_in: Mapped[float | None] = mapped_column(Numeric(12, 8), nullable=True)
    price_out: Mapped[float | None] = mapped_column(Numeric(12, 8), nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capabilities: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelRole(Base):
    __tablename__ = "model_roles"
    __table_args__ = (UniqueConstraint("role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
