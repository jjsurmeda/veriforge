from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.tokens import ACCESS_TOKEN_TYPE, TokenError, decode_token
from db.models import User
from db.session import SessionDep
from errors import AppError

_bearer = HTTPBearer(auto_error=False)


class Unauthorized(AppError):
    status_code = 401


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
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


class Forbidden(AppError):
    status_code = 403


async def get_admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise Forbidden("admin_required", "Administrator access is required")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]


async def get_admin_or_demo_user(user: CurrentUser) -> User:
    """Read access to the decision-layer statistics for the demo role (AC-2).

    Deliberately a *read* dependency, and deliberately narrow. The demo role
    already exists to read the shared corpus (PRD AC-2) and `deny_read_only`
    already refuses it uploads; this widens exactly one GET, the engine
    statistics the showcase needs to be legible, and nothing else. Every
    write in `admin/router.py` keeps `AdminUser`, so widening this cannot
    become a way to create an invite, change a threshold or grant a role.

    Split into its own dependency rather than relaxing `get_admin_user`
    because `get_admin_user` is used by ~20 handlers: loosening it would hand
    the demo role every admin write, and the failure would be invisible in
    review because each individual endpoint still reads as "admin".
    """
    if user.role not in ("admin", "demo"):
        raise Forbidden("admin_required", "Administrator access is required")
    return user


AdminOrDemoUser = Annotated[User, Depends(get_admin_or_demo_user)]
