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
