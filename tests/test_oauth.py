"""Tests for repolens.oauth (the GitHub OAuth login/callback handlers).

The GitHub-side HTTP calls (token exchange, user lookup) are mocked with
respx - no real network call in this suite. The Starlette Request objects
passed to the handlers are built directly rather than through a running
server, which is enough to exercise the handler logic in isolation.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import respx
from httpx import Response
from repolens import config, oauth, session_store
from starlette.requests import Request


def _make_request(query_string: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/callback",
        "query_string": query_string.encode(),
        "headers": [],
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# login()
# ---------------------------------------------------------------------------


async def test_login_fails_clearly_when_oauth_not_configured(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", None)

    response = await oauth.login(_make_request())

    assert response.status_code == 500
    assert b"not configured" in response.body


async def test_login_redirects_to_github_with_state(monkeypatch, isolated_session_db):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "GITHUB_OAUTH_SCOPES", "")

    response = await oauth.login(_make_request())

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "github.com"
    assert parsed.path == "/login/oauth/authorize"

    params = parse_qs(parsed.query)
    assert params["client_id"] == ["test-client-id"]
    assert "state" in params
    # The state must be a real, consumable one-time value we generated.
    assert session_store.consume_oauth_state(params["state"][0]) is True


async def test_login_includes_scope_when_configured(monkeypatch, isolated_session_db):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "GITHUB_OAUTH_SCOPES", "repo")

    response = await oauth.login(_make_request())

    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["scope"] == ["repo"]


# ---------------------------------------------------------------------------
# callback()
# ---------------------------------------------------------------------------


async def test_callback_rejects_missing_params(isolated_session_db):
    response = await oauth.callback(_make_request(""))

    assert response.status_code == 400


async def test_callback_rejects_github_error(isolated_session_db):
    request = _make_request("error=access_denied&error_description=User+denied+access")

    response = await oauth.callback(request)

    assert response.status_code == 400
    assert b"access_denied" in response.body or b"User denied access" in response.body


async def test_callback_rejects_invalid_state(isolated_session_db):
    request = _make_request("state=never-issued&code=somecode")

    response = await oauth.callback(request)

    assert response.status_code == 400
    assert b"expired" in response.body or b"invalid" in response.body.lower()


@respx.mock
async def test_callback_exchanges_code_and_issues_session(monkeypatch, isolated_session_db):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")

    state = session_store.create_oauth_state()

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_realtoken123", "scope": ""})
    )
    respx.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "octocat"})
    )

    request = _make_request(f"state={state}&code=abc123")
    response = await oauth.callback(request)

    assert response.status_code == 200
    # The success page must contain a real, usable session token - not the
    # raw GitHub token itself.
    assert b"gho_realtoken123" not in response.body
    assert b"octocat" in response.body


@respx.mock
async def test_callback_state_is_single_use_even_on_success(monkeypatch, isolated_session_db):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")

    state = session_store.create_oauth_state()
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_realtoken123"})
    )
    respx.get("https://api.github.com/user").mock(return_value=Response(200, json={}))

    request = _make_request(f"state={state}&code=abc123")
    await oauth.callback(request)

    # Replaying the same callback URL must fail - state already consumed.
    second_response = await oauth.callback(_make_request(f"state={state}&code=abc123"))
    assert second_response.status_code == 400


@respx.mock
async def test_callback_handles_token_exchange_failure(isolated_session_db):
    state = session_store.create_oauth_state()
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"error": "bad_verification_code"})
    )

    request = _make_request(f"state={state}&code=bad-code")
    response = await oauth.callback(request)

    assert response.status_code == 400


@respx.mock
async def test_callback_still_issues_session_if_user_lookup_fails(
    monkeypatch, isolated_session_db
):
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")

    state = session_store.create_oauth_state()
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_realtoken123"})
    )
    respx.get("https://api.github.com/user").mock(return_value=Response(401, json={}))

    request = _make_request(f"state={state}&code=abc123")
    response = await oauth.callback(request)

    # A failed username lookup shouldn't block issuing a working session.
    assert response.status_code == 200
