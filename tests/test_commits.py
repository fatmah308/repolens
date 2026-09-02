from __future__ import annotations

import respx
from httpx import Response
from repolens.tools.commits import (
    compute_file_churn,
    get_commit_history,
    get_file_churn,
    summarize_commit_history,
)

from .conftest import load_fixture

COMMIT_1_SHA = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
COMMIT_2_SHA = "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3"


def _mock_commit_list_and_details():
    respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=Response(200, json=load_fixture("commits.json"))
    )
    respx.get(f"https://api.github.com/repos/octocat/hello-world/commits/{COMMIT_1_SHA}").mock(
        return_value=Response(200, json=load_fixture("commit_detail_1.json"))
    )
    respx.get(f"https://api.github.com/repos/octocat/hello-world/commits/{COMMIT_2_SHA}").mock(
        return_value=Response(200, json=load_fixture("commit_detail_2.json"))
    )


# ---------------------------------------------------------------------------
# get_commit_history
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_commit_history_fetches_list_then_details(github_client):
    _mock_commit_list_and_details()

    result = await get_commit_history(github_client, "octocat/hello-world", limit=30)

    assert len(result) == 2
    assert result[0]["sha"] == "a1b2c3d4e5f6"
    assert result[0]["author"] == "Alice Dev"
    assert result[0]["message"] == "Fix off-by-one error in pagination"
    assert result[0]["files"] == ["src/pagination.py", "tests/test_pagination.py"]
    assert result[1]["files"] == ["README.md"]


@respx.mock
async def test_get_commit_history_respects_limit(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=Response(200, json=load_fixture("commits.json"))
    )
    respx.get(f"https://api.github.com/repos/octocat/hello-world/commits/{COMMIT_1_SHA}").mock(
        return_value=Response(200, json=load_fixture("commit_detail_1.json"))
    )

    result = await get_commit_history(github_client, "octocat/hello-world", limit=1)

    assert len(result) == 1
    request = route.calls.last.request
    assert request.url.params["per_page"] == "1"


@respx.mock
async def test_get_commit_history_passes_since_param(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=Response(200, json=[])
    )

    await get_commit_history(github_client, "octocat/hello-world", since="2024-01-01")

    request = route.calls.last.request
    assert request.url.params["since"] == "2024-01-01"


def test_summarize_commit_history_uses_first_line_of_message_only():
    detail = load_fixture("commit_detail_1.json")

    result = summarize_commit_history([detail])

    assert result[0]["message"] == "Fix off-by-one error in pagination"
    assert "Longer body" not in result[0]["message"]


def test_summarize_commit_history_falls_back_to_github_login():
    detail = {
        "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "commit": {"author": {}, "message": "no git author name set"},
        "author": {"login": "ghost"},
        "files": [],
    }

    result = summarize_commit_history([detail])

    assert result[0]["author"] == "ghost"


# ---------------------------------------------------------------------------
# get_file_churn
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_file_churn_fetches_commits_and_aggregates(github_client):
    _mock_commit_list_and_details()

    result = await get_file_churn(github_client, "octocat/hello-world", top_n=10)

    filenames = {row["filename"] for row in result}
    assert filenames == {"src/pagination.py", "tests/test_pagination.py", "README.md"}
    for row in result:
        assert row["commit_count"] == 1


@respx.mock
async def test_get_file_churn_passes_since_param(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=Response(200, json=[])
    )

    await get_file_churn(github_client, "octocat/hello-world", since="2024-01-01")

    request = route.calls.last.request
    assert request.url.params["since"] == "2024-01-01"


def test_compute_file_churn_ranks_by_commit_count():
    commits = [
        {"files": [{"filename": "hot.py"}, {"filename": "warm.py"}]},
        {"files": [{"filename": "hot.py"}]},
        {"files": [{"filename": "hot.py"}, {"filename": "cold.py"}]},
    ]

    result = compute_file_churn(commits, top_n=10)

    assert result[0] == {"filename": "hot.py", "commit_count": 3}
    assert result[1]["filename"] == "warm.py"
    assert result[1]["commit_count"] == 1
    assert {"filename": "cold.py", "commit_count": 1} in result


def test_compute_file_churn_respects_top_n():
    commits = [
        {"files": [{"filename": "a.py"}]},
        {"files": [{"filename": "b.py"}]},
        {"files": [{"filename": "c.py"}]},
    ]

    result = compute_file_churn(commits, top_n=2)

    assert len(result) == 2


def test_compute_file_churn_empty_commits_returns_empty():
    assert compute_file_churn([], top_n=10) == []


def test_compute_file_churn_negative_top_n_raises():
    import pytest

    with pytest.raises(ValueError):
        compute_file_churn([{"files": []}], top_n=-1)


def test_compute_file_churn_commit_touching_no_files_is_ignored():
    commits = [{"files": []}, {"files": [{"filename": "a.py"}]}]

    result = compute_file_churn(commits, top_n=10)

    assert result == [{"filename": "a.py", "commit_count": 1}]
