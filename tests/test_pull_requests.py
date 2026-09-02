from __future__ import annotations

from datetime import datetime, timezone

import respx
from httpx import Response
from repolens.tools.pull_requests import flag_stale_prs, get_pr_diff, summarize_pr_diff

from .conftest import load_fixture

SAMPLE_DIFF = (
    "diff --git a/src/pagination.py b/src/pagination.py\n"
    "index abc123..def456 100644\n"
    "--- a/src/pagination.py\n"
    "+++ b/src/pagination.py\n"
    "@@ -10,7 +10,7 @@\n"
    "-    if page > total:\n"
    "+    if page >= total:\n"
)


# ---------------------------------------------------------------------------
# get_pr_diff
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_pr_diff_fetches_pr_files_and_diff(github_client):
    respx.get("https://api.github.com/repos/octocat/hello-world/pulls/101").mock(
        return_value=Response(200, json=load_fixture("pr.json"))
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/pulls/101/files").mock(
        return_value=Response(200, json=load_fixture("pr_files.json"))
    )

    result = await get_pr_diff(github_client, "octocat/hello-world", 101)

    assert result["pr_number"] == 101
    assert result["title"] == "Fix off-by-one error in pagination"
    assert result["additions"] == 12
    assert result["deletions"] == 4
    assert result["changed_files"] == 2
    assert len(result["files"]) == 2
    assert result["files"][0]["filename"] == "src/pagination.py"
    assert isinstance(result["diff"], str)


@respx.mock
async def test_get_pr_diff_requests_diff_media_type(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/pulls/101").mock(
        return_value=Response(200, json=load_fixture("pr.json"))
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/pulls/101/files").mock(
        return_value=Response(200, json=load_fixture("pr_files.json"))
    )

    await get_pr_diff(github_client, "octocat/hello-world", 101)

    # Two GET calls hit the same /pulls/101 URL: one for JSON metadata, one
    # (with the diff Accept header) for the raw diff text.
    diff_calls = [
        call
        for call in route.calls
        if call.request.headers.get("accept") == "application/vnd.github.v3.diff"
    ]
    assert len(diff_calls) == 1


def test_summarize_pr_diff_shapes_output():
    pr = load_fixture("pr.json")
    files = load_fixture("pr_files.json")

    result = summarize_pr_diff(pr, files, SAMPLE_DIFF)

    assert result["diff"] == SAMPLE_DIFF
    assert result["files"][1]["filename"] == "tests/test_pagination.py"
    assert result["files"][1]["additions"] == 2
    assert result["files"][1]["deletions"] == 1


def test_summarize_pr_diff_falls_back_to_files_length_when_changed_files_missing():
    pr = {"number": 5, "title": "x"}
    files = load_fixture("pr_files.json")

    result = summarize_pr_diff(pr, files, "")

    assert result["changed_files"] == 2


# ---------------------------------------------------------------------------
# flag_stale_prs (network level - see test_staleness_logic.py for the pure,
# deterministic tests of the threshold computation itself)
# ---------------------------------------------------------------------------


@respx.mock
async def test_flag_stale_prs_fetches_open_prs_and_filters(github_client, monkeypatch):
    respx.get("https://api.github.com/repos/octocat/hello-world/pulls").mock(
        return_value=Response(200, json=load_fixture("prs.json"))
    )

    # Pin "now" via the module the pure function reads it from, so this
    # test doesn't depend on wall-clock time drifting the fixture ages.
    import repolens.tools.pull_requests as pr_module

    monkeypatch.setattr(
        pr_module, "utcnow", lambda: datetime(2024, 6, 20, tzinfo=timezone.utc)
    )

    result = await flag_stale_prs(github_client, "octocat/hello-world", stale_after_days=14)

    numbers = [pr["number"] for pr in result]
    # #10 was updated 2 days before "now" -> not stale.
    # #11 was updated ~19 days before -> stale.
    # #12 was updated ~80 days before -> stale, and more stale than #11.
    # #13 is closed -> never flagged even though old.
    assert numbers == [12, 11]
    assert 10 not in numbers
    assert 13 not in numbers


@respx.mock
async def test_flag_stale_prs_requests_only_open_state(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/pulls").mock(
        return_value=Response(200, json=load_fixture("prs.json"))
    )

    await flag_stale_prs(github_client, "octocat/hello-world")

    request = route.calls.last.request
    assert request.url.params["state"] == "open"


@respx.mock
async def test_flag_stale_prs_passes_through_custom_threshold(github_client, monkeypatch):
    respx.get("https://api.github.com/repos/octocat/hello-world/pulls").mock(
        return_value=Response(200, json=load_fixture("prs.json"))
    )
    import repolens.tools.pull_requests as pr_module

    monkeypatch.setattr(
        pr_module, "utcnow", lambda: datetime(2024, 6, 20, tzinfo=timezone.utc)
    )

    # With a very high threshold, nothing should be flagged.
    result = await flag_stale_prs(github_client, "octocat/hello-world", stale_after_days=9999)

    assert result == []
