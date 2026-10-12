"""Phase 1d item 1.3: the eval tooling retries its own transient provider
errors once, and records how many retries a run needed.

The distinction the item draws: a timeout while *grading* an item is a
property of the network, so the harness retries it. A product run that
completed or errored cleanly is a measurement, and is never re-run.
"""

import httpx
import litellm
import pytest

from evals import runner


@pytest.fixture(autouse=True)
def _reset_retry_counter() -> None:
    runner._provider_retries = 0


class TestTransientClassification:
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("refused"),
            httpx.HTTPStatusError(
                "429", request=httpx.Request("POST", "http://x"), response=httpx.Response(429)
            ),
            litellm.exceptions.RateLimitError(
                message="slow down", llm_provider="openrouter", model="m"
            ),
            litellm.exceptions.ServiceUnavailableError(
                message="503", llm_provider="openrouter", model="m"
            ),
            litellm.exceptions.InternalServerError(
                message="500", llm_provider="openrouter", model="m"
            ),
            litellm.exceptions.Timeout(message="timeout", llm_provider="openrouter", model="m"),
            litellm.exceptions.APIConnectionError(
                message="conn", llm_provider="openrouter", model="m"
            ),
        ],
    )
    def test_transient_errors_are_retried(self, exc: Exception) -> None:
        assert runner._is_transient_provider_error(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [
            litellm.exceptions.AuthenticationError(
                message="401", llm_provider="openrouter", model="m"
            ),
            litellm.exceptions.BadRequestError(
                message="400", llm_provider="openrouter", model="m"
            ),
            ValueError("not a provider problem"),
        ],
    )
    def test_non_transient_errors_are_not_retried(self, exc: Exception) -> None:
        assert runner._is_transient_provider_error(exc) is False


class TestRetryBehaviour:
    @pytest.mark.asyncio
    async def test_a_transient_error_is_retried_once_and_can_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "PROVIDER_RETRY_DELAY_S", 0.0)
        calls = 0

        async def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ReadTimeout("timed out")
            return "graded"

        assert await runner._retry_provider(flaky, what="judge") == "graded"
        assert calls == 2
        assert runner._provider_retries == 1

    @pytest.mark.asyncio
    async def test_a_second_transient_error_propagates_and_is_counted_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "PROVIDER_RETRY_DELAY_S", 0.0)
        calls = 0

        async def always_down() -> str:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("timed out")

        with pytest.raises(httpx.ReadTimeout):
            await runner._retry_provider(always_down, what="judge")
        # One retry, not a loop: the call was made twice and then gave up.
        assert calls == 2
        assert runner._provider_retries == 1

    @pytest.mark.asyncio
    async def test_a_non_transient_error_is_raised_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "PROVIDER_RETRY_DELAY_S", 0.0)
        calls = 0

        async def misconfigured() -> str:
            nonlocal calls
            calls += 1
            raise ValueError("bad request")

        with pytest.raises(ValueError):
            await runner._retry_provider(misconfigured, what="judge")
        assert calls == 1
        assert runner._provider_retries == 0


class TestRetryCountIsReportedButNotGated:
    def test_the_retry_count_is_not_a_gated_metric(self) -> None:
        """The count must stay OUT of `aggregate`.

        `evals.baseline` derives AGGREGATE_METRICS from `aggregate`'s own
        source and averages every one of them into the stored baseline, so a
        key added there becomes a metric the gate compares. A retry count is
        not a quality metric: a run that needed retries graded the same items
        the same way. Averaging it into faithfulness or abstention would
        corrupt the very comparison it sits beside.
        """
        from evals.baseline import AGGREGATE_METRICS

        assert "provider_retries" not in AGGREGATE_METRICS

    def test_the_retry_count_reaches_the_summary_envelope(self) -> None:
        """And it is still reported: a run that needed no retries and one that
        needed twenty reach the same verdict, and the count is the only thing
        that tells them apart."""
        import inspect

        source = inspect.getsource(runner.main)
        assert '"provider_retries"' in source