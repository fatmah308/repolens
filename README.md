# RepoLens

RepoLens is a read-only [MCP](https://modelcontextprotocol.io) server for inspecting a GitHub repository. It gives an LLM client seven tools for reading issues, pull requests, commits, code, and CI status — nothing more. It cannot create, edit, close, merge, or delete anything in the repository it's pointed at.

It's built as an installable Python package with a console-script entry point, so it runs locally via `pipx run repolens` or `pip install repolens` — there's no hosted server, no API keys stored anywhere but your own environment, and no third party in the loop.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) is an open protocol that standardizes how LLM applications (like Claude Desktop, or any MCP-compatible client) connect to external tools and data sources. Instead of every app writing its own bespoke integration for every service, an MCP *server* exposes a set of tools (and optionally resources/prompts) over a common JSON-RPC-based protocol, and any MCP *client* can talk to it the same way.

Concretely: RepoLens is an MCP server. It doesn't call an LLM itself — it just exposes seven functions ("tools") that an LLM client can invoke, each of which fetches something from the GitHub REST API and returns a structured result. The client (e.g. Claude Desktop) is the one deciding *when* to call `get_open_issues` or `flag_stale_prs`, based on what you ask it.

RepoLens talks over **stdio**: the client spawns the server as a subprocess and communicates over its stdin/stdout using JSON-RPC messages. That's also why it needs no hosting — it only exists for the lifetime of the client session that spawned it.

## The seven tools

| Tool | Input | Output | Purpose |
|---|---|---|---|
| `get_open_issues` | `repo` (`owner/name`), `label` (optional) | List of issues: title, number, labels, age in days | Surface what's currently open, optionally filtered by label |
| `get_pr_diff` | `repo`, `pr_number` | Unified diff text, files changed, +/- line counts | Let the LLM reason about an actual code change |
| `get_commit_history` | `repo`, `since` (optional date), `limit` | List of commits: SHA, author, message, files touched | Give recent-activity context |
| `flag_stale_prs` | `repo`, `stale_after_days` (default 14) | Open PRs with no activity past the threshold, sorted most-stale first | Surface PRs that are stuck waiting on someone |
| `get_file_churn` | `repo`, `since` (optional date), `top_n` (default 10) | Files ranked by number of commits touching them in the window | Code-health signal — frequently-changed files often correlate with instability |
| `search_code` | `repo`, `query`, `max_results` (default 10) | Matching files, paths, and highlighted snippets | Find where something is implemented without cloning the repo |
| `get_workflow_runs` | `repo`, `branch` (optional), `status` (optional), `limit` (default 10) | Recent GitHub Actions runs: status, conclusion, branch, link | "Is CI green" / "what's failing on main" |

Two tools do real computation rather than passing through a single API response:

- **`flag_stale_prs`** derives "days since last activity" from each open PR's `updated_at` timestamp, filters to PRs past the threshold, and ranks them. This logic lives in `compute_stale_prs()` (`src/tools/pull_requests.py`), a pure function tested independently of any network call (see `tests/test_staleness_logic.py`) — it covers boundary conditions like "exactly at the threshold" and "one day past it," sort order, closed-PR exclusion, and input validation.
- **`get_file_churn`** aggregates file-touch counts across a window of commit history (something no single GitHub endpoint returns directly) and ranks the result. This lives in `compute_file_churn()` (`src/tools/commits.py`), also a pure, independently-tested function.

All seven tools are strictly read-only. `src/github_client.py` only exposes HTTP GET helpers — there is no code path anywhere in this package that issues a POST, PATCH, PUT, or DELETE request against GitHub.

## Installation

### Option 1: run without installing, via `pipx`

```bash
pipx run repolens
```

This is mostly useful for a quick manual check — in practice, an MCP client will spawn this command for you (see below), so you won't normally run it directly.

### Option 2: install with pip

```bash
pip install repolens
```

This installs a `repolens` console script that starts the MCP server over stdio.

### Option 3: install from source (for development)

```bash
git clone https://github.com/fatmah308/repolens.git
cd repolens
pip install -e ".[dev]"

# or, without building the package:
pip install -r requirements.txt
python src/server.py
```

### GitHub token (recommended, not required)

RepoLens works without authentication, but GitHub rate-limits unauthenticated REST API requests to 60/hour, versus 5,000/hour for an authenticated request. Set a [personal access token](https://github.com/settings/tokens) (no special scopes needed for public repos; classic `repo` scope, or fine-grained read-only repo access, for private ones):

```bash
cp .env.example .env
# then edit .env and set GITHUB_TOKEN=ghp_your_token_here
```

`src/config.py` loads `.env` automatically via `python-dotenv` if one exists (and never overrides a real environment variable that's already set). Because tools are read-only, a read-only fine-grained token is sufficient and recommended.

## Connecting to Claude Desktop

Claude Desktop (and any other MCP client) launches MCP servers by running a command and talking to it over stdio. Add RepoLens to Claude Desktop's config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json` (or, for some MSIX/packaged installs, under `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\` — use Claude Desktop's own Settings → Developer → "Edit config" button to find the exact file it reads on your machine)

```json
{
  "mcpServers": {
    "repolens": {
      "command": "repolens",
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

If `repolens` isn't on your PATH (e.g. an isolated venv), point `command` at the full path instead, e.g. `/path/to/venv/bin/repolens` or `C:\\path\\to\\venv\\Scripts\\repolens.exe`.

Fully quit and reopen Claude Desktop after editing the config. Check **Settings → Developer** to confirm RepoLens shows as connected, then just ask things like:

> "Are there any stale PRs on octocat/hello-world older than 30 days?"
>
> "Is CI passing on main for anthropics/mcp?"

## Development

```bash
pip install -e ".[dev]"

# Run tests (no real network calls — GitHub responses are mocked with respx)
pytest

# Lint
ruff check src tests
```

## Project layout
