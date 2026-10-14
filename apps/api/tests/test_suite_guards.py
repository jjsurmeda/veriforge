"""The suite's own guard: work left open on the test database fails the test
that left it, instead of deadlocking a later TRUNCATE."""

import pytest
from sqlalchemy import text

from db.session import get_session_factory
from tests.conftest import assert_no_open_db_work


async def test_an_open_transaction_is_reported() -> None:
    factory = get_session_factory()
    async with factory() as leaker, factory() as checker:
        await leaker.execute(text("SELECT 1"))  # opens a transaction, left idle in it
        with pytest.raises(pytest.fail.Exception, match="idle in transaction"):
            await assert_no_open_db_work(checker)
        await leaker.rollback()


async def test_a_clean_database_passes() -> None:
    async with get_session_factory()() as checker:
        await assert_no_open_db_work(checker)
