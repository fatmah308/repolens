"""Shared test fixtures.

All HTTP calls in these tests are intercepted by respx, which replaces
httpx's transport with a mock transport - no test in this suite makes a
real network call, which is what keeps CI fast and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from repolens import config
from repolens.github_client import GitHubClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    """Load and parse a JSON fixture file from tests/fixtures/."""
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
async def github_client():
    """A real GitHubClient pointed at the real base URL.

    Safe to use under respx.mock() (see individual test modules) since
    respx intercepts at the transport layer before any socket is opened.
    """
    client = GitHubClient(token="test-token")
    yield client
    await client.aclose()


@pytest.fixture
def isolated_session_db(tmp_path, monkeypatch):
    """Point session_store at a fresh temp SQLite file for this test only.

    Prevents tests from touching a real repolens_sessions.db and keeps
    each test's session/state data isolated from the others.
    """
    db_path = tmp_path / "test_sessions.db"
    monkeypatch.setattr(config, "SESSION_DB_PATH", str(db_path))
    yield db_path
