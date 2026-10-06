"""Auth endpoints: signup/login/refresh/logout, Google OAuth (PKCE),
password reset (AC-1), roles on users (AC-2)."""

import logging
import secrets
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import invites, ratelimit
from auth.cookies import clear_refresh_cookie, set_refresh_cookie
from auth.deps import CurrentUser
from auth.email import EmailDeliveryFailed, get_email_transport
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
from db.session import SessionDep
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

GOOGLE_STATE_TTL = 600


def _client_ip(request: Request) -> str | None:
    """The caller's address for the rate limiter, or None if unknowable.

    Defined once here and imported by `chats/router.py`, rather than written
    twice: two copies of a security-relevant helper is two places to forget
    the decision below.

    **What this function does not do is read a header.** It returns
    `request.client.host` and nothing else. Measured, not assumed: a test
    that sent a forged `X-Forwarded-For` and expected the limiter to ignore it
    failed, and the reason is worth writing down rather than rediscovering.

    Uvicorn runs `ProxyHeadersMiddleware` by default (`proxy_headers=True`),
    and its `forwarded_allow_ips` defaults to `127.0.0.1`. So when the
    connection arrives from a trusted peer, the middleware has **already**
    rewritten `scope["client"]` from `X-Forwarded-For` before any handler
    sees it. That is why an untrusted attacker cannot spoof the bucket —
    their connection does not come from a trusted address, so the header is
    ignored — and it is also why the limiter sees the *real* client in
    production, which is what makes a per-IP limit mean anything at all.

    **The trust list is therefore the security boundary, not this function.**
    If Caddy moves to its own container (so its address is no longer
    `127.0.0.1`), uvicorn stops trusting the header, every request appears to
    come from Caddy, and one user exhausting their budget locks out
    everybody. That is a silent, plausible-looking failure. Setting
    `forwarded_allow_ips` to Caddy's address (or `*` only when something else
    guarantees it) belongs with the deploy work, and
    `tests/auth/test_invites_and_rate_limit.py` pins the half of this that is
    ours: we never read the header ourselves.
    """
    client = request.client
    return client.host if client is not None else None


class EmailTaken(AppError):
    status_code = 409


class InvalidCredentials(AppError):
    status_code = 401


class SignupClosed(AppError):
    status_code = 403



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
    user: CurrentUser, session: SessionDep
) -> UserPublic:
    return await _user_public(session, user)


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest,
    response: Response,
    session: SessionDep,
    request: Request,
) -> TokenResponse:
    mode = get_settings().signup_mode
    ratelimit.enforce("signup", ip=_client_ip(request))
    if mode == "closed":
        raise SignupClosed(
            "signup_closed", "Signup is closed on this deployment"
        )
    # The invite is validated BEFORE the email lookup, deliberately, and the
    # order is a security property rather than a style choice. With the
    # lookup first, a bogus code answers 409 `email_taken` for an address that
    # has an account and 400 `invite_invalid` for one that does not — which
    # is an account-existence oracle on a public endpoint, requiring no valid
    # invite at all. Validating the code first makes both cases the same 400.
    # (Found by a test written to check the oracle; see
    # test_every_unusable_code_answers_identically.)
    invite_code: str | None = None
    if mode == "invite":
        invite_code = invites.require_code(body.invite_code)
        await invites.ensure_available(session, code=invite_code)
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
    if invite_code is not None:
        # After the flush, so there is a user id to attach the invite to, and
        # before the response, so a failed claim cannot leave a live account
        # behind on a code that was already spent.
        await invites.consume(session, code=invite_code, user_id=user.id)
    return await _token_response(session, response, user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    request: Request,
) -> TokenResponse:
    ratelimit.enforce("login", ip=_client_ip(request))
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
    session: SessionDep,
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
    session: SessionDep,
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
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    vf_oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    settings = get_settings()
    if not code or not state or not vf_oauth_state or ":" not in vf_oauth_state:
        return RedirectResponse(f"{settings.web_origin}/login?error=oauth_failed")
    expected_state, verifier = vf_oauth_state.split(":", 1)
    if not secrets.compare_digest(expected_state, state):
        return RedirectResponse(f"{settings.web_origin}/login?error=oauth_failed")

    def fail_now() -> RedirectResponse:
        """The failure redirect, with the one-time state cookie cleared.

        Every response this handler returns is built here and returned, so a
        `Set-Cookie` on an injected `response` is never seen by the browser
        (review S2). Past the state check the state cookie is spent, whatever
        the outcome, so it is cleared on each of these exits too.
        """
        redirect = RedirectResponse(f"{settings.web_origin}/login?error=oauth_failed")
        redirect.delete_cookie(OAUTH_STATE_COOKIE)
        return redirect

    try:
        identity = await exchange_code(
            code=code,
            verifier=verifier,
            redirect_uri=str(request.url.replace(query=None, path="/auth/google/callback")),
        )
    except Exception:
        logger.exception("google oauth exchange failed")
        return fail_now()

    # Defence in depth at the linking site itself: an unverified address must
    # never reach the lookup below, whatever produced the identity (review S1).
    if not identity.email_verified:
        logger.error("refusing to link an unverified google email")
        return fail_now()

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
            return fail_now()
    else:
        existing = (
            await session.execute(select(User).where(User.email == identity.email))
        ).scalar_one_or_none()
        # `signup_mode` governs Google sign-in too (item 4). Google proves the
        # account with Google, not that the person was invited, so a first-time
        # account is subject to exactly the same rule as a password signup —
        # otherwise `signup_mode=invite` is open to anyone with any Google
        # account, and the mode would be decorative.
        mode = get_settings().signup_mode
        ratelimit.enforce("signup", ip=_client_ip(request))
        if existing is not None:
            user = existing
        else:
            if mode == "closed":
                return RedirectResponse(f"{settings.web_origin}/login?error=signup_closed")
            code = request.query_params.get("invite_code")
            user = User(
                email=identity.email,
                password_hash=None,
                role="user",
                plan_id=await _default_plan_id(session),
            )
            session.add(user)
            await session.flush()
            if mode == "invite":
                try:
                    await invites.attach_google_first_time(
                        session, code=invites.require_code(code), user=user
                    )
                except invites.InviteInvalid:
                    await session.rollback()
                    return RedirectResponse(
                        f"{settings.web_origin}/login?error=invite_invalid"
                    )
        session.add(OauthAccount(user_id=user.id, provider="google", subject=identity.subject))
        await session.flush()

    access = create_access_token(user)
    refresh = await issue_refresh_token(session, user.id)
    # The redirect IS the response; both cookie effects go on it, because
    # nothing mutates a response the handler does not return (review S2).
    redirect = RedirectResponse(f"{settings.web_origin}/auth/callback#access_token={quote(access)}")
    set_refresh_cookie(redirect, refresh)
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    return redirect


@router.post("/forgot-password", status_code=202)
async def forgot_password(
    body: ForgotPasswordRequest,
    session: SessionDep,
) -> dict[str, str]:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    # Always 202: never reveal whether the address has an account. That
    # includes when delivery itself fails — a 502 here would tell an attacker
    # which addresses have accounts, so a transport failure is logged and the
    # response is unchanged.
    if user is not None and user.password_hash is not None:
        token = create_password_reset_token(user)
        link = f"{get_settings().web_origin}/reset-password?token={quote(token)}"
        try:
            await get_email_transport().send(
                to=user.email,
                subject="Reset your Veriforge password",
                body=f"Reset your password: {link}",
            )
        except EmailDeliveryFailed:
            logger.exception("password reset email could not be delivered")
    return {"status": "accepted"}


@router.post("/reset-password", status_code=204)
async def reset_password(
    body: ResetPasswordRequest,
    session: SessionDep,
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
