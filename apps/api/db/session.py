from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings

_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory for code outside a request (run tasks, sweeper)."""
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """One AsyncSession per request; commits on success, rolls back on error."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


# KI-14: scope="function" ends the dependency (and its commit) before the
# response is sent; the default teardown runs after, so a client's next
# request could beat the commit.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
