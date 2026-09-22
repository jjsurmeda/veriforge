import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from auth import router as auth_router
from chats import router as chats_router
from config import get_settings
from db.session import get_session
from errors import AppError
from graph import runner
from providers import router as providers_router
from runbus.postgres import PostgresRunBus
from runs import router as runs_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
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
    yield
    sweep.cancel()
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
app.include_router(chats_router.router)
app.include_router(runs_router.router)
app.include_router(providers_router.router)


def _error_body(error_code: str, message: str, detail: object = None) -> dict[str, object]:
    return {"error_code": error_code, "message": message, "detail": detail}


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.error_code, exc.message, exc.detail),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
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
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str] | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("healthz: database unreachable")
        return JSONResponse(
            status_code=503,
            content=_error_body("db_unreachable", "Database is unreachable"),
        )
    return {"status": "ok", "db": "ok"}
