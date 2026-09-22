"""Access JWTs (15 min, HS256) and rotating refresh tokens (TRD §11).

The access token lives in browser memory only; the refresh token is an
opaque random secret whose SHA-256 hash is stored in refresh_tokens.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import RefreshToken, User

ACCESS_TOKEN_TYPE = "access"  # noqa: S105
PASSWORD_RESET_TOKEN_TYPE = "password_reset"  # noqa: S105


class TokenError(Exception):
    pass


def create_access_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["exp"]}
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if claims.get("type") != expected_type:
        raise TokenError("wrong token type")
    return claims


def create_password_reset_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "type": PASSWORD_RESET_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    # ponytail: stateless reset token is replayable within its 30-min window;
    # add single-use jti tracking when SES transport lands in slice 9.


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user_id,
            hash=_hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    await session.flush()
    return raw


class RefreshTokenRejected(Exception):
    """Presented token is unknown, expired or revoked."""


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    """Revoke the presented token and issue a fresh one.

    Reuse of an already-revoked token is treated as theft: every refresh
    token for that user is revoked.
    """
    token_hash = _hash_token(raw)
    row = (
        await session.execute(
            RefreshToken.__table__.select().where(RefreshToken.hash == token_hash)
        )
    ).first()
    if row is None:
        raise RefreshTokenRejected("unknown refresh token")
    if row.expires_at < datetime.now(UTC):
        raise RefreshTokenRejected("refresh token expired")
    if row.revoked_at is not None:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == row.user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        raise RefreshTokenRejected("refresh token reuse detected; all sessions revoked")

    user = await session.get(User, row.user_id)
    if user is None or user.status != "active":
        raise RefreshTokenRejected("user is not active")

    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id)
        .values(revoked_at=datetime.now(UTC))
    )
    new_raw = await issue_refresh_token(session, user.id)
    return user, new_raw


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.hash == _hash_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_refresh_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
