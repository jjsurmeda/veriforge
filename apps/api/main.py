import logging
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session

logger = logging.getLogger(__name__)

app = FastAPI(title="Veriforge API", version="0.1.0")


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
            content={
                "error_code": "db_unreachable",
                "message": "Database is unreachable",
                "detail": None,
            },
        )
    return {"status": "ok", "db": "ok"}
