import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from admin import router as admin_router
from auth import router as auth_router
from auth.email import build_email_transport
from chats import router as chats_router
from config import get_settings
from db.models import Run
from db.session import SessionDep
from decisions.breaker import BreakerState, get_breaker
from demo import router as demo_router
from demo.cleanup import sweep_demo_accounts
from errors import AppError
from graph import runner
from ingest import router as sources_router
from ingest.queue import app as queue_app
from providers import router as providers_router
from quota import router as quota_router
from retrieval import router as retrieval_router
from runbus.postgres import PostgresRunBus
from runs import router as runs_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # First thing, before any connection is opened: refuse to serve traffic we
    # cannot fulfil. KI-35's dev-log email transport passes every health check
    # and silently breaks password recovery for every user, so it must not be
    # reachable in production at all.
    build_email_transport(settings)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )
    bus = PostgresRunBus(session_factory, settings.database_url)
    await bus.start()
    runner.register_with_bus(bus)
    app.state.session_factory = session_factory
    app.state.bus = bus
    sweep = asyncio.create_task(runner.sweep_loop(bus, session_factory))
    # Item 4: expired demo accounts and their chats, on the same in-process
    # footing as the heartbeat sweeper (ADR-001 — no new service for this).
    demo_sweep = asyncio.create_task(sweep_demo_accounts(session_factory))
    await queue_app.open_async()
    yield
    sweep.cancel()
    demo_sweep.cancel()
    await queue_app.close_async()
    await runner.drain_background_tasks()
    await bus.stop()
    await engine.dispose()


app = FastAPI(title="Veriforge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(auth_router.me_router)
app.include_router(demo_router.router)
app.include_router(admin_router.router)
app.include_router(chats_router.router)
app.include_router(runs_router.router)
app.include_router(providers_router.router)
app.include_router(quota_router.router)
app.include_router(sources_router.router)
app.include_router(retrieval_router.router)


def _error_body(error_code: str, message: str, detail: object = None) -> dict[str, object]:
    return {"error_code": error_code, "message": message, "detail": detail}


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers: dict[str, str] = {}
    # 429 without `Retry-After` tells a well-behaved client nothing except
    # that it should guess, and the honest guess is immediately.
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.error_code, exc.message, exc.detail),
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_error_body("invalid_request", str(exc.errors())))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_error", "An unexpected error occurred"),
    )


@app.get("/healthz", response_model=None)
async def healthz(
    session: SessionDep,
) -> dict[str, object] | JSONResponse:
    """Liveness plus the three facts an operator needs during an incident.

    Backward compatible by construction: `status` and `db` keep their exact
    values and the 200/503 split on the database is unchanged, so the
    existing check (and `scripts/seed_gutenberg.py`'s, which reads this
    endpoint before seeding) keeps working. The new keys are additive.

    Deliberately *not* a readiness gate. `breaker`, `jev` and
    `worker_heartbeat_age_s` describe degraded service, and a run still
    answers with the fallback engine while the breaker is open — returning
    503 for that would take the whole API out for something the pipeline is
    designed to absorb. They are reported so an alarm can read them, and the
    status stays 200 while the service is serving.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("healthz: database unreachable")
        return JSONResponse(
            status_code=503,
            content=_error_body("db_unreachable", "Database is unreachable"),
        )
    breaker_state = get_breaker().state.value
    body: dict[str, object] = {
        "status": "ok",
        "db": "ok",
        "breaker": breaker_state,
        # `degraded` whenever Jev is not being attempted, which is the one
        # fact that explains "the answers got slower and worse". A run is
        # still correct while this reads degraded.
        "jev": "ok" if breaker_state == BreakerState.CLOSED.value else "degraded",
        "worker_heartbeat_age_s": await _worker_heartbeat_age_s(session),
    }
    return body


async def _worker_heartbeat_age_s(session: AsyncSession) -> float | None:
    """Seconds since the newest run heartbeat, or None if none is known.

    None rather than 0 for "no run has heartbeated recently", because 0 reads
    as "a heartbeat just arrived" — the healthy case — and an alarm keyed on
    the age would then never fire in the worst outage, which is every run
    dead and no heartbeat at all. None is distinguishable from both.

    Read from `runs.heartbeat_at`, the same column the sweeper decides
    stalled runs from, so this reports what the sweeper decided from rather
    than keeping a second source of truth. Any failure here returns None and
    logs: a health check must not 503 because an optional field could not be
    computed.
    """
    try:
        latest = (
            await session.execute(select(func.max(Run.heartbeat_at)))
        ).scalar_one_or_none()
    except Exception:
        logger.warning("healthz: worker heartbeat age unavailable", exc_info=True)
        return None
    if not isinstance(latest, datetime):
        return None
    return round((datetime.now(UTC) - latest).total_seconds(), 1)
