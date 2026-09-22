from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.tokens import ACCESS_TOKEN_TYPE, TokenError, decode_token
from db.models import User
from db.session import get_session
from errors import AppError

_bearer = HTTPBearer(auto_error=False)


class Unauthorized(AppError):
    status_code = 401


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise Unauthorized("unauthorized", "Missing bearer token")
    try:
        claims = decode_token(credentials.credentials, expected_type=ACCESS_TOKEN_TYPE)
    except TokenError as exc:
        raise Unauthorized("unauthorized", "Invalid or expired token") from exc
    user = await session.get(User, UUID(claims["sub"]))
    if user is None or user.status != "active":
        raise Unauthorized("unauthorized", "User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
