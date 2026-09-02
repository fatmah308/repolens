# RepoLens

RepoLens is a small, read-only [MCP](https://modelcontextprotocol.io) server for inspecting a GitHub repository. It gives an LLM client five tools for reading issues, pull requests, and commit history — nothing more. It cannot create, edit, close, merge, or delete anything in the repository it's pointed at.

It's built as an installable Python package with a console-script entry point, so it runs locally via `pipx run repolens` or `pip install repolens` — there's no hosted server, no API keys stored anywhere but your own environment, and no third party in the loop.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) is an open protocol that standardizes how LLM applications (like Claude Desktop, or any MCP-compatible client) connect to external tools and data sources. Instead of every app writing its own bespoke integration for every service, an MCP *server* exposes a set of tools (and optionally resources/prompts) over a common JSON-RPC-based protocol, and any MCP *client* can talk to it the same way.

Concretely: RepoLens is an MCP server. It doesn't call an LLM itself — it just exposes five functions ("tools") that an LLM client can invoke, each of which fetches something from the GitHub REST API and returns a structured result. The client (e.g. Claude Desktop) is the one deciding *when* to call `get_open_issues` or `flag_stale_prs`, based on what you ask it.

Most MCP servers talk over **stdio**: the client spawns the server as a subprocess and communicates over its stdin/stdout using JSON-RPC messages. That's what RepoLens does, which is also why it needs no hosting — it only exists for the lifetime of the client session that spawned it.

## The five tools

| Tool | Input | Output | Purpose |
|---|---|---|---|
| `get_open_issues` | `repo` (`owner/name`), `label` (optional) | List of issues: title, number, labels, age in days | Surface what's currently open, optionally filtered by label |
| `get_pr_diff` | `repo`, `pr_number` | Unified diff text, files changed, +/- line counts | Let the LLM reason about an actual code change |
| `get_commit_history` | `repo`, `since` (optional date), `limit` | List of commits: SHA, author, message, files touched | Give recent-activity context |
| `flag_stale_prs` | `repo`, `stale_after_days` (default 14) | Open PRs with no activity past the threshold, sorted most-stale first | Surface PRs that are stuck waiting on someone |
| `get_file_churn` | `repo`, `since` (optional date), `top_n` (default 10) | Files ranked by number of commits touching them in the window | Code-health signal — frequently-changed files often correlate with instability |

Three of these (`get_open_issues`, `get_pr_diff`, `get_commit_history`) are close to passthroughs: they call one or two GitHub endpoints and reshape the response. The other two do real computation:

- **`flag_stale_prs`** derives "days since last activity" from each open PR's `updated_at` timestamp, filters to PRs past the threshold, and ranks them. This logic lives in `compute_stale_prs()` in `src/tools/pull_requests.py`, a pure function tested independently of any network call in `tests/test_staleness_logic.py` — it covers boundary conditions like "exactly at the threshold" vs "one day past it," sort order, closed-PR exclusion, and input validation.
- **`get_file_churn`** aggregates file-touch counts across a window of commit history (something no single GitHub endpoint returns directly) and ranks the result. This lives in `compute_file_churn()` in `src/tools/commits.py`, also a pure, independently-tested function (see `tests/test_commits.py`).

All five tools are strictly read-only. `src/github_client.py` only exposes HTTP GET helpers — there is no code path anywhere in this package that issues a POST, PATCH, PUT, or DELETE request against GitHub.

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

`src/config.py` loads `.env` automatically via `python-dotenv` if one exists (and never overrides a real environment variable that's already set). In production — or when an MCP client launches RepoLens — just set `GITHUB_TOKEN` as a real environment variable instead; no `.env` file is required. Because tools are read-only, a read-only fine-grained token is sufficient and recommended.

## Connecting to Claude Desktop

Claude Desktop (and any other MCP client) launches MCP servers by running a command and talking to it over stdio. Add RepoLens to Claude Desktop's config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "repolens": {
      "command": "pipx",
      "args": ["run", "repolens"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

If you installed RepoLens with plain `pip` instead of `pipx`, point `command` directly at the installed script:

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

Restart Claude Desktop after editing the config. You should see RepoLens's five tools available (look for the 🔌/tools icon in a new chat). From there you can just ask things like:

> "Are there any stale PRs on octocat/hello-world older than 30 days?"
>
> "What files in anthropics/mcp have changed the most in the last month?"

and Claude will call `flag_stale_prs` / `get_file_churn` on your behalf and reason over the structured result.

## Development

```bash
pip install -e ".[dev]"

# Run tests (no real network calls — GitHub responses are mocked with respx)
pytest

# Lint
ruff check src tests
```

## Project layout

```
repolens/
│
├── src/
│   ├── server.py            ← MCP server entry point, registers tools
│   ├── config.py             ← Loads .env (GitHub token)
│   ├── github_client.py      ← Thin read-only wrapper over GitHub REST API
│   ├── _dates.py             ← Shared timestamp parsing helper
│   └── tools/
│       ├── __init__.py
│       ├── issues.py         ← get_open_issues
│       ├── pull_requests.py  ← get_pr_diff, flag_stale_prs (+ compute_stale_prs)
│       └── commits.py        ← get_commit_history, get_file_churn (+ compute_file_churn)
│
├── tests/
│   ├── conftest.py           ← shared fixtures, JSON fixture loader
│   ├── fixtures/             ← mocked GitHub API JSON responses
│   ├── test_issues.py        ← mocked GitHub API responses, no real network calls
│   ├── test_pull_requests.py
│   ├── test_commits.py
│   └── test_staleness_logic.py  ← pure logic tests for flag_stale_prs, deterministic
│
├── pyproject.toml            ← package metadata, enables `pip install` / `pipx run`
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
└── .github/workflows/
    └── ci.yml                ← lint + test on every push
```

Every tool module keeps a strict split: an `async` fetch function that talks to GitHub, plus, where there's real logic, a plain synchronous function that takes already-fetched data and returns the computed result (`compute_stale_prs`, `compute_file_churn`, `summarize_issues`, `summarize_pr_diff`, `summarize_commit_history`). Tests exercise both layers: the async layer via `respx`-mocked HTTP (no real network calls anywhere in the suite), and the pure functions directly and deterministically (fixed `now`, no mocking needed at all).

### A note on the `src/` layout

`src/` here is *flat* — `server.py`, `config.py`, and `github_client.py` sit directly inside it rather than inside a nested `src/repolens/` folder. `pyproject.toml` maps this to the installed package name via `[tool.setuptools] package-dir`, so `pip install .` (and `pip install -e .` for local dev) both produce a normal, importable `repolens` package (`repolens.server`, `repolens.tools.issues`, etc.) and the `repolens` console script resolves correctly either way.

## License

MIT
