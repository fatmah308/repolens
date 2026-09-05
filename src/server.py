"""RepoLens MCP server entry point.

Exposes seven read-only tools for inspecting a GitHub repository over the
Model Context Protocol. Each tool function here is a thin wrapper that
delegates to the corresponding implementation in ``repolens.tools`` -
those functions are what's unit tested; this module only handles MCP
registration and client lifecycle.

RepoLens performs no write operations against GitHub: every HTTP call made
by ``repolens.github_client.GitHubClient`` is a GET request.

Runs over stdio, launched directly by an MCP client like Claude Desktop.
Uses the GITHUB_TOKEN from your environment/.env (see config.py).
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .github_client import GitHubClient
from .tools.actions import get_workflow_runs as _get_workflow_runs
from .tools.code_search import search_code as _search_code
from .tools.commits import get_commit_history as _get_commit_history
from .tools.commits import get_file_churn as _get_file_churn
from .tools.issues import get_open_issues as _get_open_issues
from .tools.pull_requests import flag_stale_prs as _flag_stale_prs
from .tools.pull_requests import get_pr_diff as _get_pr_diff

mcp = FastMCP(
    "RepoLens",
    instructions=(
        "RepoLens gives read-only visibility into a GitHub repository: "
        "open issues, a PR's diff, recent commit history, stale PRs, file "
        "churn, code search, and CI/Actions run status. It never creates, "
        "edits, or deletes anything in the repository. Always pass `repo` "
        "as 'owner/name', e.g. 'anthropics/mcp'."
    ),
)

# A single shared GitHubClient, created lazily so importing this module
# (e.g. from tests) never opens a network connection as a side effect.
_client: GitHubClient | None = None


def _get_client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_open_issues(repo: str, label: Optional[str] = None) -> list[dict[str, Any]]:
    """List open issues in a GitHub repository, optionally filtered by label.

    Args:
        repo: repository in "owner/name" form, e.g. "anthropics/mcp".
        label: optional label name to filter by, e.g. "bug".

    Returns each issue's number, title, labels, and age in days. Read-only.
    """
    return await _get_open_issues(_get_client(), repo, label=label)


@mcp.tool()
async def get_pr_diff(repo: str, pr_number: int) -> dict[str, Any]:
    """Get the unified diff and per-file +/- stats for a pull request.

    Args:
        repo: repository in "owner/name" form.
        pr_number: the pull request number.

    Returns the diff text, list of changed files with add/delete counts,
    and overall totals. Read-only.
    """
    return await _get_pr_diff(_get_client(), repo, pr_number)


@mcp.tool()
async def get_commit_history(
    repo: str, since: Optional[str] = None, limit: int = 30
) -> list[dict[str, Any]]:
    """List recent commits: SHA, author, message, and files touched.

    Args:
        repo: repository in "owner/name" form.
        since: optional ISO-8601 date/datetime to only include commits after.
        limit: maximum number of commits to return (default 30, max 100).

    Read-only.
    """
    return await _get_commit_history(_get_client(), repo, since=since, limit=limit)


@mcp.tool()
async def flag_stale_prs(repo: str, stale_after_days: int = 14) -> list[dict[str, Any]]:
    """Flag open pull requests with no activity past a day threshold.

    Args:
        repo: repository in "owner/name" form.
        stale_after_days: a PR counts as stale once more than this many
            days have passed since its last update (default 14).

    Returns stale PRs sorted most-stale first, each with days_inactive.
    Computes staleness rather than passing through a single GitHub API
    response. Read-only.
    """
    return await _flag_stale_prs(_get_client(), repo, stale_after_days=stale_after_days)


@mcp.tool()
async def get_file_churn(
    repo: str, since: Optional[str] = None, top_n: int = 10
) -> list[dict[str, Any]]:
    """Rank files by how many commits touched them in a time window.

    Args:
        repo: repository in "owner/name" form.
        since: optional ISO-8601 date/datetime to restrict the window.
        top_n: how many files to return, highest churn first (default 10).

    A code-health signal: files that change constantly often correlate
    with instability, unclear ownership, or poor separation of concerns.
    Aggregates across commit history rather than passing through a single
    API response. Read-only.
    """
    return await _get_file_churn(_get_client(), repo, since=since, top_n=top_n)


@mcp.tool()
async def search_code(repo: str, query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search a repository's code for a query string.

    Args:
        repo: repository in "owner/name" form.
        query: search terms, using GitHub code search syntax (e.g.
            "def parse_config", "TODO language:python").
        max_results: maximum number of matches to return (default 10).

    Returns matching files with path, URL, and highlighted snippet
    fragments where available. Note: GitHub's code search API has a
    stricter rate limit (10 requests/minute) than other endpoints. Read-only.
    """
    return await _search_code(_get_client(), repo, query, max_results=max_results)


@mcp.tool()
async def get_workflow_runs(
    repo: str,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent GitHub Actions / CI workflow run status for a repository.

    Args:
        repo: repository in "owner/name" form.
        branch: optional branch name to filter to.
        status: optional filter, e.g. "completed", "in_progress", "queued",
            "success", "failure", "cancelled".
        limit: maximum number of runs to return (default 10).

    Returns each run's status, conclusion, branch, and link. Useful for
    "is CI green" / "what's failing on main" questions. Read-only.
    """
    return await _get_workflow_runs(_get_client(), repo, branch=branch, status=status, limit=limit)


def main() -> None:
    """Console-script entry point (see pyproject.toml). Runs over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
