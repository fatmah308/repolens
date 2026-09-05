"""Shared test fixtures.

All HTTP calls in these tests are intercepted by respx, which replaces
httpx's transport with a mock transport - no test in this suite makes a
real network call, which is what keeps CI fast and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
