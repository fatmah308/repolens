"""Session storage for the hosted (streamable-http) multi-tenant mode.

Maps an opaque, server-issued session token to a specific user's own
GitHub OAuth access token, so each person's tool calls run as *their*
GitHub identity and permissions rather than one shared token. Also stores
short-lived OAuth ``state`` values used to protect the login flow against
CSRF (RFC 6749 section 10.12).

Backed by SQLite for simplicity and zero extra infrastructure - fine for
a single server instance. If you scale to multiple instances behind a
load balancer, swap this module for a shared backend (Redis, Postgres);
the functions below are the whole interface the rest of the app relies on.

Nothing here is used in local stdio mode - it only matters when
``config.TRANSPORT == "http"``.
"""

from __future__ import annotations

import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import config

#: How long an issued session token stays valid after creation.
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

#: How long an OAuth `state` value stays valid - just long enough for a
#: person to complete the GitHub consent screen.
STATE_TTL_SECONDS = 10 * 60  # 10 minutes


def _connect() -> sqlite3.Connection:
    db_path = Path(config.SESSION_DB_PATH)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            github_token TEXT NOT NULL,
            github_login TEXT,
            created_at REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS oauth_state (
            state TEXT PRIMARY KEY,
            created_at REAL NOT NULL
        )"""
    )
    conn.commit()
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def create_oauth_state() -> str:
    """Generate and store a one-time CSRF state value for the login flow."""
    state = secrets.token_urlsafe(24)
    with _db() as conn:
        conn.execute(
            "INSERT INTO oauth_state (state, created_at) VALUES (?, ?)",
            (state, time.time()),
        )
        conn.commit()
    return state


def consume_oauth_state(state: str, now: float | None = None) -> bool:
    """Validate and delete a one-time state value.

    Returns True if it existed and hadn't expired. Always deletes it if
    found, so a state value can only ever be used once - whether or not
    it was still valid.
    """
    reference_time = now if now is not None else time.time()
    with _db() as conn:
        row = conn.execute(
            "SELECT created_at FROM oauth_state WHERE state = ?", (state,)
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM oauth_state WHERE state = ?", (state,))
        conn.commit()
        created_at = row[0]
    return (reference_time - created_at) <= STATE_TTL_SECONDS


def create_session(github_token: str, github_login: str | None) -> str:
    """Issue a new opaque session token for a logged-in GitHub user."""
    session_token = secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, github_token, github_login, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_token, github_token, github_login, time.time()),
        )
        conn.commit()
    return session_token


def get_github_token(session_token: str, now: float | None = None) -> str | None:
    """Look up the GitHub access token for a session.

    Returns None if the session token doesn't exist or has expired.
    """
    reference_time = now if now is not None else time.time()
    with _db() as conn:
        row = conn.execute(
            "SELECT github_token, created_at FROM sessions WHERE token = ?",
            (session_token,),
        ).fetchone()
    if row is None:
        return None
    github_token, created_at = row
    if (reference_time - created_at) > SESSION_TTL_SECONDS:
        return None
    return github_token


def revoke_session(session_token: str) -> None:
    """Delete a session immediately (e.g. a manual "log out" action)."""
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
        conn.commit()
