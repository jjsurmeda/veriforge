"""Periodic cleanup of expired demo accounts (lane E item 4).

A `while True: sleep; purge` loop beside the heartbeat sweeper in `main.py`,
for the same reason that sweeper is one: ADR-001 puts this work in the API
process rather than a new service, and the API is the only place with a
database session.

The interval is a quarter of the TTL so an account is never more than an hour
past it before it goes, even if a cycle is missed. The loop catches its own
errors: a cleanup task that dies quietly stops cleaning, and the symptom would
only be visible as rows in a table weeks later.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from demo.service import purge_expired

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 15 * 60


async def sweep_demo_accounts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_seconds: float = INTERVAL_SECONDS,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with session_factory() as session:
                removed = await purge_expired(session, now=datetime.now(UTC))
            if removed:
                logger.info("demo cleanup removed %d expired account(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Logged, then the loop continues: one bad cycle must not end the
            # task, and an operator needs to see that it happened.
            logger.exception("demo account cleanup failed; will retry on the next cycle")