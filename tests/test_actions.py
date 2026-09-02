from __future__ import annotations

import respx
from httpx import Response
from repolens.tools.actions import get_workflow_runs, summarize_workflow_runs

from .conftest import load_fixture


@respx.mock
async def test_get_workflow_runs_fetches_and_summarizes(github_client):
    respx.get("https://api.github.com/repos/octocat/hello-world/actions/runs").mock(
        return_value=Response(200, json=load_fixture("workflow_runs.json"))
    )

    result = await get_workflow_runs(github_client, "octocat/hello-world")

    assert len(result) == 3
    assert result[0]["id"] == 1001
    assert result[0]["status"] == "completed"
    assert result[0]["conclusion"] == "success"
    assert result[1]["conclusion"] == "failure"
    assert result[2]["status"] == "in_progress"
    assert result[2]["conclusion"] is None


@respx.mock
async def test_get_workflow_runs_passes_branch_and_status_filters(github_client):
    route = respx.get("https://api.github.com/repos/octocat/hello-world/actions/runs").mock(
        return_value=Response(200, json=load_fixture("workflow_runs.json"))
    )

    await get_workflow_runs(
        github_client, "octocat/hello-world", branch="main", status="completed"
    )

    request = route.calls.last.request
    assert request.url.params["branch"] == "main"
    assert request.url.params["status"] == "completed"


@respx.mock
async def test_get_workflow_runs_respects_limit(github_client):
    respx.get("https://api.github.com/repos/octocat/hello-world/actions/runs").mock(
        return_value=Response(200, json=load_fixture("workflow_runs.json"))
    )

    result = await get_workflow_runs(github_client, "octocat/hello-world", limit=2)

    assert len(result) == 2


def test_summarize_workflow_runs_shapes_output():
    raw = load_fixture("workflow_runs.json")["workflow_runs"]

    result = summarize_workflow_runs(raw)

    assert result[0]["branch"] == "main"
    assert result[0]["event"] == "push"
    assert result[0]["url"] == "https://github.com/octocat/hello-world/actions/runs/1001"


def test_summarize_workflow_runs_empty_list():
    assert summarize_workflow_runs([]) == []


def test_summarize_workflow_runs_falls_back_to_display_title():
    raw = [{"id": 1, "display_title": "Nightly build", "status": "completed"}]

    result = summarize_workflow_runs(raw)

    assert result[0]["name"] == "Nightly build"
