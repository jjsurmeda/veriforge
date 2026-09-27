"""KI-14: writes must be committed before the response is sent.

`get_session` used to commit in dependency teardown, which on FastAPI 0.141
runs after the response has left the server. A signup that returns 201 can
lose the race against the same client's very next request. This test fails
while that race exists: any single 401 across the loop is a lost commit.
"""

from httpx import AsyncClient

from tests.conftest import signup


async def test_signup_row_is_visible_to_the_immediately_following_request(
    client: AsyncClient,
) -> None:
    for i in range(50):
        body = await signup(client, f"ki14-race-{i}@test.dev")
        token = body["access_token"]
        assert isinstance(token, str)
        response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, (
            f"iteration {i}: /auth/me returned {response.status_code} "
            f"({response.text}) right after signup returned 201 — "
            "the signup commit lost the race against this request"
        )
