"""Auth endpoints: signup/login/refresh/logout, Google OAuth (PKCE),
password reset (AC-1), roles on users (AC-2)."""

import logging
import secrets
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.cookies import clear_refresh_cookie, set_refresh_cookie
from auth.deps import CurrentUser
from auth.email import DevLogEmailTransport
from auth.google import OAUTH_STATE_COOKIE, auth_url, exchange_code, make_pkce_pair
from auth.passwords import hash_password, verify_password
from auth.tokens import (
    PASSWORD_RESET_TOKEN_TYPE,
    RefreshTokenRejected,
    TokenError,
    create_access_token,
    create_password_reset_token,
    decode_token,
    issue_refresh_token,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)
from config import get_settings
from db.models import OauthAccount, Plan, User
from db.session import get_session
from errors import AppError
from schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserPublic,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["me"])

_email_transport = DevLogEmailTransport()

GOOGLE_STATE_TTL = 600


class EmailTaken(AppError):
    status_code = 409


class InvalidCredentials(AppError):
    status_code = 401


async def _default_plan_id(session: AsyncSession) -> UUID:
    plan = (await session.execute(select(Plan).where(Plan.name == "free"))).scalar_one()
    return plan.id


async def _user_public(session: AsyncSession, user: User) -> UserPublic:
    plan = await session.get(Plan, user.plan_id)
    assert plan is not None
    return UserPublic(
        id=str(user.id),
        email=user.email,
        role=user.role,
        plan={
            "name": plan.name,
            "credits_5h": plan.credits_5h,
            "credits_month": plan.credits_month,
        },
    )


async def _token_response(session: AsyncSession, response: Response, user: User) -> TokenResponse:
    access = create_access_token(user)
    refresh = await issue_refresh_token(session, user.id)
    set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, user=await _user_public(session, user))


@me_router.get("/me", response_model=UserPublic)
async def me(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> UserPublic:
    return await _user_public(session, user)


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise EmailTaken("email_taken", "An account with this email already exists")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role="user",
        plan_id=await _default_plan_id(session),
    )
    session.add(user)
    await session.flush()
    return await _token_response(session, response, user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None or not verify_password(
        body.password, user.password_hash
    ):
        raise InvalidCredentials("invalid_credentials", "Email or password is incorrect")
    return await _token_response(session, response, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    vf_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not vf_refresh:
        raise InvalidCredentials("missing_refresh_token", "No refresh token cookie")
    try:
        user, new_refresh = await rotate_refresh_token(session, vf_refresh)
    except RefreshTokenRejected as exc:
        # Persist the reuse-detection family revocation before failing.
        await session.commit()
        clear_refresh_cookie(response)
        raise InvalidCredentials("refresh_rejected", str(exc)) from exc
    access = create_access_token(user)
    set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=access, user=await _user_public(session, user))


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    vf_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if vf_refresh:
        await revoke_refresh_token(session, vf_refresh)
    clear_refresh_cookie(response)


@router.get("/google/login")
async def google_login(request: Request) -> RedirectResponse:
    settings = get_settings()
    if not settings.google_client_id:
        raise AppError(
            "oauth_not_configured", "Google OAuth is not configured", status_code=503
        )
    state = secrets.token_urlsafe(24)
    verifier, challenge = make_pkce_pair()
    redirect_uri = str(request.url.replace(query=None, path="/auth/google/callback"))
    url = auth_url(state=state, challenge=challenge, redirect_uri=redirect_uri)
    response = RedirectResponse(url)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=f"{state}:{verifier}",
        max_age=GOOGLE_STATE_TTL,
        httponly=True,
        secure=settings.cookie_secure,
        # lax, not strict: the cookie must survive the return hop from Google.
        samesite="lax",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = None,
    state: str | None = None,
    vf_oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    settings = get_settings()
    fail = RedirectResponse(f"{settings.web_origin}/login?error=oauth_failed")
    if not code or not state or not vf_oauth_state or ":" not in vf_oauth_state:
        return fail
    expected_state, verifier = vf_oauth_state.split(":", 1)
    if not secrets.compare_digest(expected_state, state):
        return fail
    response.delete_cookie(OAUTH_STATE_COOKIE)

    try:
        identity = await exchange_code(
            code=code,
            verifier=verifier,
            redirect_uri=str(request.url.replace(query=None, path="/auth/google/callback")),
        )
    except Exception:
        logger.exception("google oauth exchange failed")
        return fail

    oauth = (
        await session.execute(
            select(OauthAccount).where(
                OauthAccount.provider == "google", OauthAccount.subject == identity.subject
            )
        )
    ).scalar_one_or_none()

    if oauth is not None:
        user = await session.get(User, oauth.user_id)
        if user is None:
            return fail
    else:
        existing = (
            await session.execute(select(User).where(User.email == identity.email))
        ).scalar_one_or_none()
        user = existing or User(
            email=identity.email,
            password_hash=None,
            role="user",
            plan_id=await _default_plan_id(session),
        )
        session.add(user)
        await session.flush()
        session.add(OauthAccount(user_id=user.id, provider="google", subject=identity.subject))
        await session.flush()

    access = create_access_token(user)
    refresh = await issue_refresh_token(session, user.id)
    set_refresh_cookie(response, refresh)
    return RedirectResponse(f"{settings.web_origin}/auth/callback#access_token={quote(access)}")


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    # Always 202: never reveal whether the address has an account.
    if user is not None and user.password_hash is not None:
        token = create_password_reset_token(user)
        link = f"{get_settings().web_origin}/reset-password?token={quote(token)}"
        await _email_transport.send(
            to=user.email,
            subject="Reset your Veriforge password",
            body=f"Reset your password: {link}",
        )
    return {"status": "accepted"}


@router.post("/reset-password", status_code=204)
async def reset_password(
    body: ResetPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        claims = decode_token(body.token, expected_type=PASSWORD_RESET_TOKEN_TYPE)
    except TokenError as exc:
        raise AppError(
                "invalid_reset_token", "Reset link is invalid or expired"
            ) from exc
    user = await session.get(User, UUID(claims["sub"]))
    if user is None:
        raise AppError("invalid_reset_token", "Reset link is invalid or expired")
    user.password_hash = hash_password(body.password)
    # Force every existing session to re-authenticate after a reset.
    await revoke_all_refresh_tokens(session, user.id)
