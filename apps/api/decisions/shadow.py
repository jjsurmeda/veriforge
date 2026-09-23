"""Shadow-mode persistence (TRD §8).

Called by DecisionEngine for the 2% sample; writes one row per question
into `decision_shadow`. Surfaced on the admin eval page in slice 7/8 —
for now this table is write-only from the app's perspective.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import DecisionShadow
from schemas.decisions import Answer

ShadowWriterFn = Callable[[str, str, Answer, Answer, bool], Awaitable[None]]


def make_shadow_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> ShadowWriterFn:
    """Build the ShadowWriter the engine expects. One write per call,
    own short-lived session per python.md."""

    async def write(
        run_id: str, decision: str, jev: Answer, fallback: Answer, agree: bool
    ) -> None:
        if not run_id:
            return
        async with session_factory() as session, session.begin():
            session.add(
                DecisionShadow(
                    run_id=run_id,
                    decision=decision,
                    jev_answer=jev.model_dump(mode="json"),
                    fallback_answer=fallback.model_dump(mode="json"),
                    agree=agree,
                )
            )

    return write
