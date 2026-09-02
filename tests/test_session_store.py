"""Tests for repolens.session_store.

All state lives in a temporary SQLite file per test (via the
``isolated_session_db`` fixture in conftest.py), so tests never touch a
real database and never hit the network - this is pure local logic.
"""

from __future__ import annotations

import time

from repolens import session_store


def test_create_and_get_session_round_trips(isolated_session_db):
    token = session_store.create_session("gh-token-abc", "octocat")

    assert session_store.get_github_token(token) == "gh-token-abc"


def test_get_session_returns_none_for_unknown_token(isolated_session_db):
    assert session_store.get_github_token("does-not-exist") is None


def test_session_expires_after_ttl(isolated_session_db):
    token = session_store.create_session("gh-token-abc", "octocat")

    # Just under the TTL: still valid.
    almost_expired = time.time() + session_store.SESSION_TTL_SECONDS - 1
    assert session_store.get_github_token(token, now=almost_expired) == "gh-token-abc"

    # Just past the TTL: expired.
    just_expired = time.time() + session_store.SESSION_TTL_SECONDS + 1
    assert session_store.get_github_token(token, now=just_expired) is None


def test_revoke_session_removes_it(isolated_session_db):
    token = session_store.create_session("gh-token-abc", "octocat")

    session_store.revoke_session(token)

    assert session_store.get_github_token(token) is None


def test_session_tokens_are_unique(isolated_session_db):
    token1 = session_store.create_session("gh-token-1", "user1")
    token2 = session_store.create_session("gh-token-2", "user2")

    assert token1 != token2
    assert session_store.get_github_token(token1) == "gh-token-1"
    assert session_store.get_github_token(token2) == "gh-token-2"


def test_create_and_consume_oauth_state(isolated_session_db):
    state = session_store.create_oauth_state()

    assert session_store.consume_oauth_state(state) is True


def test_oauth_state_is_one_time_use(isolated_session_db):
    state = session_store.create_oauth_state()

    session_store.consume_oauth_state(state)

    # Second attempt with the same state must fail - single use only.
    assert session_store.consume_oauth_state(state) is False


def test_unknown_oauth_state_is_rejected(isolated_session_db):
    assert session_store.consume_oauth_state("never-issued") is False


def test_oauth_state_expires_after_ttl(isolated_session_db):
    state = session_store.create_oauth_state()

    just_expired = time.time() + session_store.STATE_TTL_SECONDS + 1

    assert session_store.consume_oauth_state(state, now=just_expired) is False


def test_oauth_state_within_ttl_is_accepted(isolated_session_db):
    state = session_store.create_oauth_state()

    almost_expired = time.time() + session_store.STATE_TTL_SECONDS - 1

    assert session_store.consume_oauth_state(state, now=almost_expired) is True
