"""get_open_issues: surface currently-open issues, optionally by label.

This is a near-passthrough tool: the only transformation applied to the
GitHub API response is (a) filtering out pull requests, which GitHub's
``/issues`` endpoint annoyingly includes, and (b) computing each issue's
age in days for convenience.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .._dates import parse_github_datetime, utcnow
from ..github_client import GitHubClient


def _age_days(created_at: str, now: datetime | None = None) -> int:
    now = now or utcnow()
    return (now - parse_github_datetime(created_at)).days


def summarize_issues(
    raw_issues: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Pure transform of raw GitHub issue payloads into the tool's output shape.

    Excludes pull requests (GitHub's issues endpoint returns both issues and
    PRs; PR entries carry a ``pull_request`` key).
    """
    summarized = []
    for issue in raw_issues:
        if "pull_request" in issue:
            continue
        labels = [
            label["name"] if isinstance(label, dict) else label
            for label in issue.get("labels", [])
        ]
        summarized.append(
            {
                "number": issue["number"],
                "title": issue["title"],
                "labels": labels,
                "age_days": _age_days(issue["created_at"], now=now),
                "url": issue.get("html_url"),
            }
        )
    return summarized


async def get_open_issues(
    client: GitHubClient, repo: str, label: str | None = None
) -> list[dict[str, Any]]:
    """Fetch open issues for ``repo`` (``owner/name``), optionally filtered by label."""
    params: dict[str, Any] = {"state": "open", "per_page": 100}
    if label:
        params["labels"] = label
    raw_issues = await client.get_json(f"/repos/{repo}/issues", params=params)
    return summarize_issues(raw_issues)
