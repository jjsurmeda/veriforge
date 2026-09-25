
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from tests.retrieval.conftest import make_user


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "scope-a@test.dev")


@pytest.fixture
async def user_b(db: AsyncSession) -> User:
    return await make_user(db, "scope-b@test.dev")
