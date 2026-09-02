"""get_workflow_runs: recent GitHub Actions workflow run history for a repo.

A passthrough tool: GitHub's Actions API already returns exactly the run
list we want, so this reshapes a single endpoint's response rather than
computing anything. Useful for "is CI green right now" / "what's failing
on main" style questions.
"""

from __future__ import annotations

from typing import Any

from ..github_client import GitHubClient


def summarize_workflow_runs(raw_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure transform of raw GitHub Actions run payloads into the tool's output shape."""
    summarized = []
    for run in raw_runs:
        summarized.append(
            {
                "id": run.get("id"),
                "name": run.get("name") or run.get("display_title"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "branch": run.get("head_branch"),
                "event": run.get("event"),
                "run_number": run.get("run_number"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "url": run.get("html_url"),
            }
        )
    return summarized


async def get_workflow_runs(
    client: GitHubClient,
    repo: str,
    branch: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch recent GitHub Actions runs for ``repo``.

    Args:
        client: the GitHub API client.
        repo: repository in "owner/name" form.
        branch: optional branch name to filter to.
        status: optional run status/conclusion filter - one of GitHub's
            accepted values, e.g. "completed", "in_progress", "queued",
            "success", "failure", "cancelled".
        limit: maximum number of runs to return (default 10, max 100).
    """
    params: dict[str, Any] = {"per_page": min(max(limit, 1), 100)}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    raw_response = await client.get_json(f"/repos/{repo}/actions/runs", params=params)
    raw_runs = raw_response.get("workflow_runs", [])
    return summarize_workflow_runs(raw_runs)[:limit]
