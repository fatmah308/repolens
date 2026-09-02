"""Configuration loading for RepoLens.

Reads settings from process environment variables, optionally pre-loaded
from a local ``.env`` file via python-dotenv. This means:

- In development, copy ``.env.example`` to ``.env`` and fill in your
  GitHub token; it's picked up automatically.
- In production / when run by an MCP client, set real environment
  variables (e.g. the ``env`` block in Claude Desktop's config) - no
  ``.env`` file is required, and python-dotenv never overrides a variable
  that's already set in the real environment.

Nothing in this module makes a network call; it only reads configuration.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Loads variables from a .env file in the current working directory (or any
# parent directory) into os.environ, if one exists. This is a no-op - not
# an error - when no .env file is present, and never clobbers a variable
# that's already set in the real environment.
load_dotenv()

#: GitHub personal access token. Optional: RepoLens works unauthenticated,
#: but GitHub rate-limits unauthenticated requests to 60/hour vs 5000/hour
#: authenticated. A read-only / fine-grained token is sufficient since
#: RepoLens never writes to GitHub.
GITHUB_TOKEN: str | None = os.environ.get("GITHUB_TOKEN")

#: Overridable for testing against a mock server or GitHub Enterprise.
GITHUB_API_BASE: str = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

#: Per-request HTTP timeout, in seconds.
REQUEST_TIMEOUT_SECONDS: float = float(os.environ.get("REPOLENS_TIMEOUT_SECONDS", "30"))

# ---------------------------------------------------------------------------
# Hosted (multi-tenant, streamable-http) mode settings.
#
# Local single-user use (the default) needs none of this - just GITHUB_TOKEN
# above, and RepoLens runs over stdio exactly as before. These only matter
# if you set REPOLENS_TRANSPORT=http to run RepoLens as a shared HTTP
# service that other people connect to with their own GitHub identity.
# ---------------------------------------------------------------------------

#: "stdio" (default, local, single-user) or "http" (hosted, multi-tenant).
TRANSPORT: str = os.environ.get("REPOLENS_TRANSPORT", "stdio")

#: Bind address/port for HTTP mode.
HOST: str = os.environ.get("REPOLENS_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("REPOLENS_PORT", "8000"))

#: The public URL people reach this server at once deployed, e.g.
#: "https://repolens.example.com". Used to build the OAuth callback URL and
#: to allow-list the host/origin against DNS-rebinding protection. Must be
#: set correctly in any real deployment or both will silently fail.
PUBLIC_URL: str = os.environ.get("REPOLENS_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")

#: Extra hosts/origins to allow, beyond what's derived from PUBLIC_URL -
#: comma-separated, e.g. "REPOLENS_ALLOWED_HOSTS=api.example.com,example.com".
#: Needed if you sit behind a proxy/CDN that presents a different Host
#: header than PUBLIC_URL, or serve multiple domains.
ALLOWED_HOSTS: list[str] = [
    h.strip() for h in os.environ.get("REPOLENS_ALLOWED_HOSTS", "").split(",") if h.strip()
]
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("REPOLENS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

#: GitHub OAuth App credentials (https://github.com/settings/developers ->
#: "New OAuth App"). Required for the hosted /auth/login flow that lets
#: each person connect with their own GitHub account instead of sharing
#: GITHUB_TOKEN. Set the OAuth App's "Authorization callback URL" to
#: "{PUBLIC_URL}/auth/callback".
GITHUB_OAUTH_CLIENT_ID: str | None = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
GITHUB_OAUTH_CLIENT_SECRET: str | None = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")

#: GitHub's OAuth endpoints. Overridable for GitHub Enterprise Server (whose
#: OAuth endpoints live on your own domain) or for testing against a fake
#: server. The user-info lookup during login reuses GITHUB_API_BASE, not a
#: separate setting, since that's the same REST API RepoLens's tools call.
GITHUB_OAUTH_AUTHORIZE_URL: str = os.environ.get(
    "GITHUB_OAUTH_AUTHORIZE_URL", "https://github.com/login/oauth/authorize"
)
GITHUB_OAUTH_TOKEN_URL: str = os.environ.get(
    "GITHUB_OAUTH_TOKEN_URL", "https://github.com/login/oauth/access_token"
)

#: Classic GitHub OAuth Apps have coarse scopes - there is no "read-only"
#: scope the way fine-grained PATs have. Empty (the default) grants access
#: to public data only, which is enough for public repos and is the safest
#: default for a multi-tenant server. Set to "repo" to allow private-repo
#: access too, but note that scope also grants write access at the GitHub
#: API level - RepoLens itself still never calls a non-GET endpoint, but a
#: leaked session token would carry that broader GitHub-side permission.
GITHUB_OAUTH_SCOPES: str = os.environ.get("GITHUB_OAUTH_SCOPES", "")

#: Where session data (issued session tokens <-> each user's GitHub OAuth
#: token) is stored. SQLite is fine for a single instance; for multiple
#: instances behind a load balancer, point this at a shared volume or swap
#: src/session_store.py for a shared backend (Redis, Postgres).
SESSION_DB_PATH: str = os.environ.get("REPOLENS_SESSION_DB_PATH", "repolens_sessions.db")


def oauth_callback_url() -> str:
    """The callback URL to register with your GitHub OAuth App."""
    return f"{PUBLIC_URL}/auth/callback"


def oauth_login_url() -> str:
    """The URL a person visits to start the login flow."""
    return f"{PUBLIC_URL}/auth/login"
