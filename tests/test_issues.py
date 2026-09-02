from __future__ import annotations

from datetime import datetime, timezone

import respx
from httpx import Response
from repolens.tools.issues import get_open_issues, summarize_issues

from .conftest import load_fixture


@respx.mock
async def test_get_open_issues_fetches_and_summarizes(github_client):
    respx.get("https://api.github.com/repos/octocat/hello-world/issues").mock(
        return_value=Response(200, json=load_fixture("issues.json"))
    )

    result = await get_open_issues(github_client, "octocat/hello-world")

    # The PR entry (#44) must be filtered out; only true issues remain.
    assert [issue["number"] for issue in result] == [42, 43]
    assert result[0]["title"] == "Crash when parsing empty config file"
    assert result[0]["labels"] == ["bug", "priority:high"]
    assert isinstance(result[0]["age_days"], int)
    assert result[0]["age_days"] >= 0


@respx.mock
async def test_get_open_issues_passes_label_filter(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/issues").mock(
        return_value=Response(200, json=load_fixture("issues.json"))
    )

    await get_open_issues(github_client, "octocat/hello-world", label="bug")

    assert route.called
    request = route.calls.last.request
    assert request.url.params["labels"] == "bug"
    assert request.url.params["state"] == "open"


@respx.mock
async def test_get_open_issues_sends_auth_header(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/issues").mock(
        return_value=Response(200, json=[])
    )

    await get_open_issues(github_client, "octocat/hello-world")

    assert route.calls.last.request.headers["authorization"] == "Bearer test-token"


def test_summarize_issues_excludes_pull_requests():
    raw = load_fixture("issues.json")
    now = datetime(2024, 6, 1, tzinfo=timezone.utc)

    result = summarize_issues(raw, now=now)

    numbers = [issue["number"] for issue in result]
    assert 44 not in numbers  # the PR-flagged entry
    assert numbers == [42, 43]


def test_summarize_issues_computes_age_in_days():
    raw = [
        {
            "number": 1,
            "title": "x",
            "created_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "html_url": "https://example.com",
        }
    ]
    now = datetime(2024, 1, 11, tzinfo=timezone.utc)

    result = summarize_issues(raw, now=now)

    assert result[0]["age_days"] == 10


def test_summarize_issues_handles_plain_string_labels():
    # Some GitHub API responses / mocks represent labels as plain strings
    # rather than {"name": ...} objects; make sure both shapes work.
    raw = [
        {
            "number": 1,
            "title": "x",
            "created_at": "2024-01-01T00:00:00Z",
            "labels": ["bug"],
            "html_url": "https://example.com",
        }
    ]

    result = summarize_issues(raw, now=datetime(2024, 1, 2, tzinfo=timezone.utc))

    assert result[0]["labels"] == ["bug"]
