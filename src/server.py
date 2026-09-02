"""RepoLens MCP server entry point.

Exposes seven read-only tools for inspecting a GitHub repository over the
Model Context Protocol. Each tool function here is a thin wrapper that
delegates to the corresponding implementation in ``repolens.tools`` -
those functions are what's unit tested; this module only handles MCP
registration, transport selection, and (in hosted mode) per-caller auth.

RepoLens performs no write operations against GitHub: every HTTP call made
by ``repolens.github_client.GitHubClient`` is a GET request.

Two ways to run this:

- **Local, single-user (default)**: ``repolens`` over stdio, using the
  ``GITHUB_TOKEN`` from your environment/``.env``. This is what Claude
  Desktop and similar clients launch directly. Nothing below about auth
  or HTTP applies to this mode.
- **Hosted, multi-tenant**: set ``REPOLENS_TRANSPORT=http`` and this runs
  as a persistent HTTP service instead. Each caller authenticates with
  their own GitHub account via ``/auth/login`` (see ``oauth.py``) and
  passes the resulting session token as an ``Authorization: Bearer``
  header; their tool calls then run with their own GitHub permissions.
  An operator can still set ``GITHUB_TOKEN`` as a shared fallback for
  unauthenticated callers (e.g. a small trusted internal deployment).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from . import config, oauth, session_store
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

# A single shared GitHubClient for local stdio mode (and, in hosted mode,
# for any operator-configured fallback token). Created lazily so importing
# this module never opens a network connection as a side effect.
_shared_client: GitHubClient | None = None


def _get_shared_client() -> GitHubClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = GitHubClient()
    return _shared_client


def _resolve_client() -> GitHubClient:
    """Pick the right GitHubClient for the current call.

    - stdio mode (no HTTP request in play): always the shared client, using
      GITHUB_TOKEN from the environment. Unchanged from single-user
      behavior.
    - hosted (http) mode, caller sent ``Authorization: Bearer <session>``:
      look up that session's own GitHub OAuth token and use it - each
      caller's tool calls run as their own GitHub identity.
    - hosted mode, no/invalid Authorization header: fall back to the
      shared GITHUB_TOKEN if the operator configured one (small trusted
      deployments), otherwise raise a clear error telling the caller to
      log in.
    """
    try:
        request = mcp.get_context().request_context.request
    except Exception:
        request = None

    if request is None:
        return _get_shared_client()

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        session_token = auth_header[len("bearer "):].strip()
        github_token = session_store.get_github_token(session_token)
        if github_token:
            return GitHubClient(token=github_token)
        raise RuntimeError(
            "Your RepoLens session is invalid or has expired. Log in again "
            f"at {config.oauth_login_url()}, then update the Authorization "
            "header in your MCP client with the new session token."
        )

    if config.GITHUB_TOKEN:
        return _get_shared_client()

    raise RuntimeError(
        "No GitHub identity found for this request. Log in at "
        f"{config.oauth_login_url()} and add the resulting session token as "
        "an `Authorization: Bearer <token>` header in your MCP client config."
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_open_issues(repo: str, label: str | None = None) -> list[dict[str, Any]]:
    """List open issues in a GitHub repository, optionally filtered by label.

    Args:
        repo: repository in "owner/name" form, e.g. "anthropics/mcp".
        label: optional label name to filter by, e.g. "bug".

    Returns each issue's number, title, labels, and age in days. Read-only.
    """
    return await _get_open_issues(_resolve_client(), repo, label=label)


@mcp.tool()
async def get_pr_diff(repo: str, pr_number: int) -> dict[str, Any]:
    """Get the unified diff and per-file +/- stats for a pull request.

    Args:
        repo: repository in "owner/name" form.
        pr_number: the pull request number.

    Returns the diff text, list of changed files with add/delete counts,
    and overall totals. Read-only.
    """
    return await _get_pr_diff(_resolve_client(), repo, pr_number)


@mcp.tool()
async def get_commit_history(
    repo: str, since: str | None = None, limit: int = 30
) -> list[dict[str, Any]]:
    """List recent commits: SHA, author, message, and files touched.

    Args:
        repo: repository in "owner/name" form.
        since: optional ISO-8601 date/datetime to only include commits after.
        limit: maximum number of commits to return (default 30, max 100).

    Read-only.
    """
    return await _get_commit_history(_resolve_client(), repo, since=since, limit=limit)


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
    return await _flag_stale_prs(_resolve_client(), repo, stale_after_days=stale_after_days)


@mcp.tool()
async def get_file_churn(
    repo: str, since: str | None = None, top_n: int = 10
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
    return await _get_file_churn(_resolve_client(), repo, since=since, top_n=top_n)


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
    return await _search_code(_resolve_client(), repo, query, max_results=max_results)


@mcp.tool()
async def get_workflow_runs(
    repo: str,
    branch: str | None = None,
    status: str | None = None,
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
    return await _get_workflow_runs(
        _resolve_client(), repo, branch=branch, status=status, limit=limit
    )


# ---------------------------------------------------------------------------
# Hosted-mode-only HTTP routes: OAuth login flow and a health check.
# These are always registered, but only reachable when actually running
# under an HTTP transport (stdio mode never serves HTTP at all).
# ---------------------------------------------------------------------------


@mcp.custom_route("/auth/login", methods=["GET"])
async def _auth_login(request: Request):
    return await oauth.login(request)


@mcp.custom_route("/auth/callback", methods=["GET"])
async def _auth_callback(request: Request):
    return await oauth.callback(request)


@mcp.custom_route("/health", methods=["GET"])
async def _health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _configure_http_settings() -> None:
    """Apply hosted-mode settings: bind address and DNS-rebinding allow-list.

    The allow-list defaults (localhost only) block every request on a real
    deployment unless the public host/origin is added - this derives it
    from REPOLENS_PUBLIC_URL automatically and layers in any extra hosts
    from REPOLENS_ALLOWED_HOSTS / REPOLENS_ALLOWED_ORIGINS.
    """
    mcp.settings.host = config.HOST
    mcp.settings.port = config.PORT

    parsed_public_url = urlparse(config.PUBLIC_URL)
    public_host = parsed_public_url.netloc
    scheme = parsed_public_url.scheme or "https"

    allowed_hosts = set(mcp.settings.transport_security.allowed_hosts)
    allowed_origins = set(mcp.settings.transport_security.allowed_origins)
    if public_host:
        allowed_hosts.add(public_host)
        allowed_origins.add(f"{scheme}://{public_host}")
    allowed_hosts.update(config.ALLOWED_HOSTS)
    allowed_origins.update(config.ALLOWED_ORIGINS)

    mcp.settings.transport_security.allowed_hosts = list(allowed_hosts)
    mcp.settings.transport_security.allowed_origins = list(allowed_origins)


def main() -> None:
    """Console-script entry point (see pyproject.toml).

    Runs over stdio by default (local, single-user). Set
    REPOLENS_TRANSPORT=http to run as a hosted, multi-tenant HTTP service
    instead - see README for the full hosted-deployment walkthrough.
    """
    if config.TRANSPORT == "http":
        _configure_http_settings()
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
