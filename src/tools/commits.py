"""Commit tools: get_commit_history (passthrough) and get_file_churn (computed).

get_commit_history
-------------------
Recent commits with SHA, author, message, and files touched. The
commit-list endpoint doesn't include per-commit file lists, so this tool
fetches each commit's detail concurrently. Still a passthrough in the
sense that no aggregation happens here (see get_file_churn below).

get_file_churn
--------------
The second of RepoLens's two genuinely computed tools (the other being
flag_stale_prs in pull_requests.py). Ranks files by how many commits
touched them in a time window - something no single GitHub endpoint
returns directly, so this fetches commit detail across the window and
aggregates a per-file touch count.

High-churn files are a common code-health signal - a file that changes in
nearly every commit is often either a hotspot of real instability (bugs,
unclear ownership, poor separation of concerns) or a "junk drawer" file
(config, changelog) that isn't actually meaningful churn. RepoLens surfaces
the raw signal; interpreting it is left to the caller/LLM.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from ..github_client import GitHubClient

# ---------------------------------------------------------------------------
# get_commit_history
# ---------------------------------------------------------------------------


def summarize_commit_history(detailed_commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure transform of raw per-commit detail payloads into the tool's output shape."""
    summarized = []
    for commit in detailed_commits:
        commit_info = commit.get("commit", {})
        git_author = commit_info.get("author", {}) or {}
        gh_author = commit.get("author") or {}
        author = git_author.get("name") or gh_author.get("login") or "unknown"
        message = commit_info.get("message", "")
        summarized.append(
            {
                "sha": commit["sha"][:12],
                "author": author,
                "message": message.split("\n", 1)[0],
                "files": [f["filename"] for f in commit.get("files", [])],
            }
        )
    return summarized


async def get_commit_history(
    client: GitHubClient,
    repo: str,
    since: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` recent commits for ``repo``, optionally since a given date.

    ``since`` should be an ISO-8601 date/datetime string (e.g. ``2024-01-01``).
    """
    params: dict[str, Any] = {"per_page": min(max(limit, 1), 100)}
    if since:
        params["since"] = since
    raw_commits = await client.get_json(f"/repos/{repo}/commits", params=params)
    raw_commits = raw_commits[:limit]
    detailed = await asyncio.gather(
        *(client.get_json(f"/repos/{repo}/commits/{c['sha']}") for c in raw_commits)
    )
    return summarize_commit_history(list(detailed))


# ---------------------------------------------------------------------------
# get_file_churn
# ---------------------------------------------------------------------------


def compute_file_churn(
    detailed_commits: list[dict[str, Any]], top_n: int = 10
) -> list[dict[str, Any]]:
    """Pure aggregation: count commits touching each file, return the top N.

    Args:
        detailed_commits: raw per-commit detail payloads (each including a
            ``files`` list), as returned by
            ``GET /repos/{repo}/commits/{sha}``.
        top_n: how many files to return, ranked highest-churn first.

    Returns:
        A list of ``{"filename": ..., "commit_count": ...}`` dicts, sorted
        descending by ``commit_count``. Ties fall back to the order files
        were first seen (stable sort via ``Counter.most_common``).
    """
    if top_n < 0:
        raise ValueError("top_n must be >= 0")

    counter: Counter[str] = Counter()
    for commit in detailed_commits:
        for f in commit.get("files", []):
            counter[f["filename"]] += 1

    return [
        {"filename": filename, "commit_count": count}
        for filename, count in counter.most_common(top_n)
    ]


async def get_file_churn(
    client: GitHubClient,
    repo: str,
    since: str | None = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Fetch commits for ``repo`` (optionally since a date) and rank files by churn."""
    params: dict[str, Any] = {"per_page": 100}
    if since:
        params["since"] = since
    raw_commits = await client.get_json(f"/repos/{repo}/commits", params=params)
    detailed = await asyncio.gather(
        *(client.get_json(f"/repos/{repo}/commits/{c['sha']}") for c in raw_commits)
    )
    return compute_file_churn(list(detailed), top_n=top_n)
