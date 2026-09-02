"""search_code: search a repository's code for a query string.

Uses GitHub's code search REST endpoint (``GET /search/code``), scoped to
a single repo via a ``repo:owner/name`` qualifier appended to the query.
A near-passthrough tool: GitHub does the actual searching and ranking,
this just requests match-highlighting fragments and reshapes the result.

Note on rate limits: GitHub's code search API has a much stricter rate
limit than most REST endpoints - 10 requests/minute for authenticated
users (as of this writing), regardless of your general API rate limit.
Heavy use of this tool in particular can hit that limit faster than the
others.
"""

from __future__ import annotations

from typing import Any

from ..github_client import GitHubClient

# Requests match-highlighting fragments (text_matches) in the response.
TEXT_MATCH_HEADERS = {"Accept": "application/vnd.github.v3.text-match+json"}


def summarize_code_search(raw_results: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure transform of the raw GitHub code-search response into the tool's output shape."""
    items = raw_results.get("items", [])
    summarized = []
    for item in items:
        fragments = [
            match.get("fragment", "")
            for match in item.get("text_matches", [])
            if match.get("fragment")
        ]
        summarized.append(
            {
                "path": item.get("path"),
                "repository": (item.get("repository") or {}).get("full_name"),
                "sha": item.get("sha"),
                "url": item.get("html_url"),
                "fragments": fragments,
            }
        )
    return summarized


async def search_code(
    client: GitHubClient,
    repo: str,
    query: str,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search for ``query`` within ``repo``'s code, returning matching files and snippets."""
    scoped_query = f"{query} repo:{repo}"
    params = {"q": scoped_query, "per_page": min(max(max_results, 1), 100)}
    raw_results = await client.get_json(
        "/search/code", params=params, headers=TEXT_MATCH_HEADERS
    )
    return summarize_code_search(raw_results)[:max_results]
