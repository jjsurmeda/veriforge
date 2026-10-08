"""`POST /auth/demo` — the unauthenticated route that starts a demo (item 4).

Order of operations is the whole design here, and it is deliberate:

1. **Rate limit first**, before any database work. A throttled request must
   cost nothing beyond the counter, exactly as `chats/router.py` does it for
   run creation — checking later would mean an account row had been created
   and then had to be undone.
2. **Then create the account**, on the seeded `demo` plan.
3. **Then the normal tokens.** No special token, no demo-only claim: the
   frontend's existing auth path is what gets exercised, which is also why the
   demo needs no frontend-side token handling.

There is deliberately no `PUT`/`DELETE` counterpart and no way to list demo
accounts: an endpoint that mints an account without a credential is already
the attack surface, and more surface around it is more surface.

Deep mode and web search are refused for a demo account in `chats/router.py`,
where the run is created, because that is the one place that decides what a run
may do. Refusing them in a pre-check here would leave a second path.
"""

import logging

from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from auth.cookies import set_refresh_cookie
from auth.deps import CurrentUser
from auth.ratelimit import RateLimited, RateLimiter
from auth.router import _client_ip
from auth.tokens import create_access_token, issue_refresh_token
from db.models import Plan, User
from db.session import SessionDep
from demo import service
from demo.settings import DemoSettings, demo_settings
from errors import AppError
from schemas.auth import TokenResponse, UserPublic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class DemoNotSeeded(AppError):
    status_code = 503


# One limiter for the scope, rebuilt when the configured limit changes — the
# same shape as `auth/ratelimit.py`'s process-wide limiters, kept local here
# because the demo limit is a demo setting and belongs to this feature.
_limiter: RateLimiter | None = None


def _demo_limiter(settings: DemoSettings) -> RateLimiter:
    global _limiter
    if (
        _limiter is None
        or _limiter.limit != settings.rate_limit
        or _limiter.window_seconds != settings.window_seconds
    ):
        _limiter = RateLimiter(limit=settings.rate_limit, window_seconds=settings.window_seconds)
    return _limiter


def reset_demo_limiter() -> None:
    """Drop the bucket. Test-support only; never called in a request."""
    global _limiter
    _limiter = None


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


@router.post("/demo", response_model=TokenResponse, status_code=201)
async def start_demo(
    response: Response,
    session: SessionDep,
    request: Request,
) -> TokenResponse:
    settings = demo_settings()
    wait = _demo_limiter(settings).check(("demo", f"ip:{_client_ip(request) or 'unknown'}"))
    if wait is not None:
        raise RateLimited("demo", wait)
    try:
        user = await service.create_demo_user(session, settings)
    except service.DemoUnavailable as exc:
        # 503 rather than a fallback plan: an operator who has not run
        # `make seed-demo` needs to be told, not silently handed a free-tier
        # account with a 200k budget.
        raise DemoNotSeeded("demo_unavailable", str(exc)) from exc

    access = create_access_token(user)
    refresh = await issue_refresh_token(session, user.id)
    set_refresh_cookie(response, refresh)
    logger.info("demo account started (role=demo, plan=%s)", settings.plan_name)
    return TokenResponse(access_token=access, user=await _user_public(session, user))


@router.get("/demo/limits")
async def demo_limits(user: CurrentUser) -> dict[str, object]:
    """What a demo account may do, for the composer.

    Read by any authenticated user, not just the demo role, so the composer can
    hide the Deep and Web toggles for a demo account before the request is
    made — a control that is visible and then refused is worse than one that is
    absent. The values are the same settings the route enforces, read from the
    same place, so the UI cannot drift from the server.
    """
    settings = demo_settings()
    demo = user.role == "demo"
    return {
        "role": user.role,
        "is_demo": demo,
        # A demo account may use Deep only when the operator has turned it on
        # for the beta week; a normal user's Deep is not this setting's
        # business, so it is always allowed for them.
        "allow_deep": settings.allow_deep if demo else True,
        # Web search needs a configured provider (config.py's `tavily_api_key`
        # and friends), which the demo deployment does not set, so it is off for
        # a demo account regardless — refusing it here and not in the UI means
        # a stale client still cannot reach a paid provider.
        "allow_web": not demo,
        "allow_upload": not demo,
        "plan": settings.plan_name,
    }