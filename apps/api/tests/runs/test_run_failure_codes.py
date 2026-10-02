"""Terminal run failures carry a real code (KI-23, backend half).

Every terminal failure the run cannot fix used to reach the client as
`error_code="run_error"` and "The run could not finish. Try again." A
provider whose key is invalid, a provider that is out of credit and a provider
that is merely unreachable all said the same thing — and for all three,
retrying cannot help, so the message sent the user into a retry loop that
spends nothing and succeeds never.

The three codes are the whole vocabulary, and the frontend keys its copy off
them:

    quota_exceeded          no credit to run on, from either side. Carries
                            `reset_at` when the failure had a window behind it
                            (the app's own 5h/month limit) and `reset_at: null`
                            when it did not (a provider balance).
    provider_key_invalid    the configured key was rejected. Operator problem.
    provider_unavailable    the provider is down or unreachable. Retry may work.

Driven over SSE through a real run, because the claim under test is what the
stream carries; a unit test of the classifier alone would pass with the
runner's failure path still collapsing everything.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BudgetExceededError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from decisions.output_guard import OutputGuardResult
from errors import AppError
from graph import runner as runner_module
from graph.review import ReviewResult
from graph.runner import _reset_at
from providers.llm import classify_provider_error
from quota.service import QuotaExceeded
from schemas.events import RunFailed

PROVIDER = "openrouter"
MODEL = "openrouter/some-model"

# The codes this commit publishes. Pinned as a set so a future change cannot
# quietly add a fourth name: the frontend maps these to copy, so a new string
# is a change to another team's contract and has to be a deliberate edit here.
PUBLISHED_CODES = {"quota_exceeded", "provider_key_invalid", "provider_unavailable"}


def _auth_error() -> AuthenticationError:
    return AuthenticationError(message="401 invalid key", llm_provider=PROVIDER, model=MODEL)


def _permission_error() -> PermissionDeniedError:
    # PermissionDeniedError reaches into the httpx response, so it needs a real
    # one — the classification only reads the type, but constructing the
    # exception must not be the thing that fails.
    return PermissionDeniedError(
        message="403 forbidden",
        llm_provider=PROVIDER,
        model=MODEL,
        response=httpx.Response(403, request=httpx.Request("POST", "https://openrouter.ai")),
    )


def _rate_limit_error() -> RateLimitError:
    return RateLimitError(message="402 insufficient credits", llm_provider=PROVIDER, model=MODEL)


def _budget_error() -> BudgetExceededError:
    return BudgetExceededError(current_cost=1.0, max_budget=0.0, llm_provider=PROVIDER)


def _unavailable_error() -> ServiceUnavailableError:
    return ServiceUnavailableError(message="503", llm_provider=PROVIDER, model=MODEL)


# --- the classification ----------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (_auth_error(), "provider_key_invalid"),
        (_permission_error(), "provider_key_invalid"),
        (_rate_limit_error(), "quota_exceeded"),
        (_budget_error(), "quota_exceeded"),
        (_unavailable_error(), "provider_unavailable"),
        (
            InternalServerError(message="500", llm_provider=PROVIDER, model=MODEL),
            "provider_unavailable",
        ),
        (Timeout(message="timed out", model=MODEL, llm_provider=PROVIDER), "provider_unavailable"),
        (
            APIConnectionError(message="no route", llm_provider=PROVIDER, model=MODEL),
            "provider_unavailable",
        ),
    ],
)
def test_each_provider_failure_maps_to_its_own_code(
    exc: BaseException, expected_code: str
) -> None:
    """One code per distinct failure, not one per retry loop. Note the 429: it
    is `quota_exceeded`, not `provider_unavailable`, because a provider that
    has run out of credit does not fix itself and "try again" is the wrong
    instruction."""
    classified = classify_provider_error(exc)

    assert classified is not None
    assert classified.error_code == expected_code
    assert classified.error_code in PUBLISHED_CODES


def test_the_three_codes_are_distinct() -> None:
    """Stated on its own because the whole point is that these are three
    different facts. If two of these ever collapse into one string again, the
    frontend loses the ability to say anything different to the user."""
    codes = {
        classify_provider_error(exc).error_code  # type: ignore[union-attr]
        for exc in (_auth_error(), _rate_limit_error(), _unavailable_error())
    }
    assert codes == PUBLISHED_CODES


def test_an_exception_this_module_cannot_speak_for_is_not_classified() -> None:
    """A bug in our own code must stay `run_error`. Classifying it as a
    provider outage would send an operator chasing the provider."""
    assert classify_provider_error(ValueError("bug")) is None
    assert classify_provider_error(AppError("x", "y")) is None


def test_the_provider_codes_carry_no_reset_time() -> None:
    """A provider balance has no window, so there is no instant to name.
    Publishing a guess would be worse than publishing nothing."""
    for exc in (_rate_limit_error(), _budget_error()):
        classified = classify_provider_error(exc)
        assert classified is not None
        assert _reset_at(classified) is None


# --- reset_at --------------------------------------------------------------


def test_the_apps_own_quota_failure_carries_its_reset_time() -> None:
    """`quota/service.py` is the one failure that knows when the window rolls
    over, and the user needs it: "try again" with no time is the complaint
    KI-23 was filed about."""
    exc = QuotaExceeded(
        "quota_exceeded",
        "Your credit limit has been reached for this window",
        {"reset_at": "2026-10-02T17:00:00+00:00", "window": "5h"},
    )

    assert exc.error_code == "quota_exceeded"
    assert _reset_at(exc) == "2026-10-02T17:00:00+00:00"


def test_a_detail_of_the_wrong_shape_yields_no_reset_time() -> None:
    """A non-dict detail, or a non-string `reset_at`, is absent rather than
    stringified."""
    assert _reset_at(AppError("x", "y")) is None
    assert _reset_at(AppError("x", "y", {"reset_at": 1759000000})) is None
    assert _reset_at(AppError("x", "y", {"reset_at": None})) is None


def test_the_event_carries_the_field_and_it_is_optional() -> None:
    """Additive and optional: every existing producer of `run.failed` and every
    existing consumer of its shape are unaffected, which is what lets the
    frontend lane rely on these names without a coordinated release."""
    event = RunFailed(run_id="r", error_code="provider_key_invalid", message="m")
    assert event.reset_at is None
    assert "reset_at" in RunFailed.model_fields

    with_reset = RunFailed(
        run_id="r", error_code="quota_exceeded", reset_at="2026-10-02T17:00:00+00:00"
    )
    assert with_reset.reset_at == "2026-10-02T17:00:00+00:00"


# --- end to end over SSE ---------------------------------------------------


async def _auth(client: AsyncClient, email: str) -> dict[str, str]:
    signup = await client.post("/auth/signup", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {signup.json()['access_token']}"}


async def _parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
    if data:
        yield event, json.loads("\n".join(data))


async def _run_and_read_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> dict[str, Any]:
    """One Fast-mode run whose generator raises `failure`, and the
    `run.failed` payload the user receives."""
    email = f"fail-{type(failure).__name__.lower()}@test.dev"

    async def failing_stream(**kwargs: Any) -> AsyncIterator[str]:
        raise failure
        yield ""  # pragma: no cover - keeps this an async generator

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return "rewritten"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    async def fake_review_answer(**kwargs: Any) -> Any:
        return ReviewResult()

    async def fake_suggestions(**kwargs: Any) -> list[str]:
        return []

    async def fake_guard_output(*args: Any, **kwargs: Any) -> Any:
        return OutputGuardResult()

    monkeypatch.setattr("graph.fast.stream_grounded_answer", failing_stream)
    monkeypatch.setattr("graph.fast.complete", fake_complete)
    monkeypatch.setattr("graph.chat_title.complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard_output)

    headers = await _auth(client, email)
    chat = await client.post("/chats", json={}, headers=headers)
    started = await client.post(
        f"/chats/{chat.json()['id']}/runs",
        json={"message": "say hi"},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]

    failure_event: dict[str, Any] = {}
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, data in _parse_sse(response.aiter_lines()):
            if event_type == "run.failed":
                failure_event = data
            if event_type in {"run.failed", "run.completed"}:
                break
    return failure_event


@pytest.mark.parametrize(
    ("make_failure", "expected_code"),
    [
        (lambda: _auth_error(), "provider_key_invalid"),
        (lambda: _rate_limit_error(), "quota_exceeded"),
        (lambda: _unavailable_error(), "provider_unavailable"),
    ],
)
async def test_a_provider_failure_reaches_the_stream_with_its_own_code(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    make_failure: Any,
    expected_code: str,
) -> None:
    event = await _run_and_read_failure(client, monkeypatch, make_failure())

    assert event, "the run produced no run.failed event"
    assert event["error_code"] == expected_code
    assert event["error_code"] in PUBLISHED_CODES
    # A provider-side exhaustion has no window, so it must not invent one.
    assert event["reset_at"] is None


async def test_an_apps_quota_failure_reaches_the_stream_with_its_reset_time(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app's own credit window, raised mid-run, is the one failure that
    knows when it rolls over — and the field has to survive the trip to the
    client, or the frontend has nothing to render."""
    exc = QuotaExceeded(
        "quota_exceeded",
        "Your credit limit has been reached for this window",
        {"reset_at": "2026-10-02T17:00:00+00:00", "window": "5h"},
    )

    event = await _run_and_read_failure(client, monkeypatch, exc)

    assert event["error_code"] == "quota_exceeded"
    assert event["reset_at"] == "2026-10-02T17:00:00+00:00"


async def test_a_bug_in_our_own_code_is_still_run_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The complement, and the reason the classifier returns None instead of
    raising: an unrecognised failure must not be dressed up as a provider
    outage, or an operator goes looking in the wrong place."""
    event = await _run_and_read_failure(client, monkeypatch, ValueError("bug"))

    assert event["error_code"] == "run_error"
    assert event["reset_at"] is None
    assert event["error_code"] not in PUBLISHED_CODES
