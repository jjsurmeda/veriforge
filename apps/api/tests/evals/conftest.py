"""Isolation for the eval-gate tests, plus eval-corpus ownership fixtures.

`evals.gate` records every run's summary to `.data/evals/summary-*.json` so a
baseline can later be written from the mean of N runs (A8). A test that drives
`gate.main` with a stubbed `run_eval` therefore has a synthetic summary, not a
measured one, and the real directory is exactly where the next operator globs
for the summaries to average — a stray file there would be averaged into the
committed baseline without anyone noticing. So the recording directory is
redirected for every test in this package, whether or not the test asks for it.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from evals import baseline
from tests.retrieval.conftest import make_user


@pytest.fixture(autouse=True)
def recorded_summaries_go_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    """Point `evals.baseline.record` at this test's tmp_path.

    `record` reads the module global at call time, so patching the constant is
    enough to redirect it — the alternative, patching `gate.record_summary`,
    would leave a gate-driven write reaching the repo for any test that forgets.
    """
    out = tmp_path / "summaries"
    monkeypatch.setattr(baseline, "SUMMARY_DIR", out)
    yield out


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "corpus-a@test.dev")


@pytest.fixture
async def user_b(db: AsyncSession) -> User:
    return await make_user(db, "corpus-b@test.dev")


@pytest.fixture
def user_factory(db: AsyncSession) -> Callable[..., object]:
    async def make(email: str) -> User:
        return await make_user(db, email)

    return make
