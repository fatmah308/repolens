"""Pull-request tools: get_pr_diff (passthrough) and flag_stale_prs (computed).

get_pr_diff
-----------
Fetches a PR's unified diff plus file-level stats. A passthrough tool:
GitHub already computes the diff and per-file +/- counts, so this
function's job is just to fetch the three relevant endpoints and reshape
them into one response.

flag_stale_prs
--------------
The one genuinely "intelligent" tool in this module (and one of two in the
whole package - see also get_file_churn in commits.py). Every other tool
here is a thin reshape of a single GitHub API response; this one computes
something: given a repo's open pull requests, it derives "days since last
activity" for each PR from its ``updated_at`` timestamp, filters to PRs
past a caller-supplied threshold, and returns them ranked from most- to
least-stale.

``updated_at`` on a GitHub PR advances on any activity that touches the PR
object itself - new commits, comments, review submissions, label changes,
etc. - which makes it a reasonable single-field proxy for "last activity"
without needing to separately fetch and merge the commits, reviews, and
comments timelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .._dates import parse_github_datetime, utcnow
from ..github_client import GitHubClient

DIFF_HEADERS = {"Accept": "application/vnd.github.v3.diff"}


# ---------------------------------------------------------------------------
# get_pr_diff
# ---------------------------------------------------------------------------


def summarize_pr_diff(
    pr: dict[str, Any], files_raw: list[dict[str, Any]], diff_text: str
) -> dict[str, Any]:
    """Pure transform of the raw PR + files-list payloads into the tool's output shape."""
    files = [
        {
            "filename": f["filename"],
            "status": f.get("status"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
        }
        for f in files_raw
    ]
    return {
        "pr_number": pr["number"],
        "title": pr.get("title"),
        "state": pr.get("state"),
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", len(files)),
        "files": files,
        "diff": diff_text,
    }


async def get_pr_diff(client: GitHubClient, repo: str, pr_number: int) -> dict[str, Any]:
    """Fetch the diff, changed-files list, and +/- counts for ``repo``#``pr_number``."""
    pr = await client.get_json(f"/repos/{repo}/pulls/{pr_number}")
    diff_text = await client.get_text(f"/repos/{repo}/pulls/{pr_number}", headers=DIFF_HEADERS)
    files_raw = await client.get_json(
        f"/repos/{repo}/pulls/{pr_number}/files", params={"per_page": 100}
    )
    return summarize_pr_diff(pr, files_raw, diff_text)


# ---------------------------------------------------------------------------
# flag_stale_prs
# ---------------------------------------------------------------------------


def compute_stale_prs(
    raw_prs: list[dict[str, Any]],
    stale_after_days: int = 14,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Pure staleness computation over raw GitHub PR payloads.

    Args:
        raw_prs: raw pull request objects as returned by the GitHub
            ``GET /repos/{repo}/pulls`` endpoint.
        stale_after_days: a PR is considered stale once more than this many
            whole days have elapsed since its ``updated_at`` timestamp.
        now: the reference "current time" (defaults to real UTC now).
            Exposed as a parameter so tests can pin it instead of relying
            on wall-clock time.

    Returns:
        Stale PRs only, each annotated with ``days_inactive``, sorted from
        most-stale (largest ``days_inactive``) to least-stale.

    Raises:
        ValueError: if ``stale_after_days`` is negative.
    """
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be >= 0")

    reference_time = now or utcnow()
    stale: list[dict[str, Any]] = []

    for pr in raw_prs:
        # Only open PRs can be "stale" in the sense we care about; a closed
        # or merged PR isn't waiting on anyone.
        if pr.get("state") != "open":
            continue

        updated_at = pr.get("updated_at")
        if not updated_at:
            continue

        days_inactive = (reference_time - parse_github_datetime(updated_at)).days
        if days_inactive > stale_after_days:
            stale.append(
                {
                    "number": pr["number"],
                    "title": pr.get("title"),
                    "author": (pr.get("user") or {}).get("login"),
                    "updated_at": updated_at,
                    "days_inactive": days_inactive,
                    "url": pr.get("html_url"),
                }
            )

    stale.sort(key=lambda item: item["days_inactive"], reverse=True)
    return stale


async def flag_stale_prs(
    client: GitHubClient, repo: str, stale_after_days: int = 14
) -> list[dict[str, Any]]:
    """Fetch open PRs for ``repo`` and flag those inactive past ``stale_after_days``."""
    raw_prs = await client.get_json(
        f"/repos/{repo}/pulls", params={"state": "open", "per_page": 100}
    )
    return compute_stale_prs(raw_prs, stale_after_days=stale_after_days)
