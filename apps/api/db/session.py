from collections.abc import AsyncIterator

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
