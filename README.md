# RepoLens

RepoLens is a read-only [MCP](https://modelcontextprotocol.io) server for inspecting a GitHub repository. It gives an LLM client seven tools for reading issues, pull requests, commits, code, and CI status — nothing more. It cannot create, edit, close, merge, or delete anything in the repository it's pointed at.

It runs two ways:

- **Local, single-user** (the default): an installable Python package with a console-script entry point, launched directly by a client like Claude Desktop via `pipx run repolens` or `pip install repolens`. No hosting, no accounts, no third party in the loop - it only exists for the life of the client session that spawned it.
- **Hosted, multi-tenant**: a persistent HTTP service other people connect to, each authenticating with their own GitHub account via OAuth login rather than sharing a token.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) is an open protocol that standardizes how LLM applications (like Claude Desktop, or any MCP-compatible client) connect to external tools and data sources. An MCP *server* exposes a set of tools over a common protocol; any MCP *client* can talk to it the same way, instead of every app writing its own bespoke integration per service.

RepoLens is an MCP server. It doesn't call an LLM itself - it exposes seven functions ("tools") an LLM client can invoke, each of which fetches something from the GitHub REST API and returns a structured result. The client decides *when* to call `get_open_issues` or `flag_stale_prs`, based on what you ask it.

Local mode talks over **stdio**: the client spawns RepoLens as a subprocess and communicates over stdin/stdout. Hosted mode talks over **streamable HTTP** instead, so multiple people can connect to the same running instance at once.

## The seven tools

| Tool | Input | Output | Purpose |
|---|---|---|---|
| `get_open_issues` | `repo` (`owner/name`), `label` (optional) | Issues: title, number, labels, age in days | Surface what's currently open, optionally filtered by label |
| `get_pr_diff` | `repo`, `pr_number` | Unified diff text, files changed, +/- line counts | Let the LLM reason about an actual code change |
| `get_commit_history` | `repo`, `since` (optional date), `limit` | Commits: SHA, author, message, files touched | Give recent-activity context |
| `flag_stale_prs` | `repo`, `stale_after_days` (default 14) | Open PRs with no activity past the threshold, sorted most-stale first | Surface PRs that are stuck waiting on someone |
| `get_file_churn` | `repo`, `since` (optional date), `top_n` (default 10) | Files ranked by commits touching them in the window | Code-health signal - frequently-changed files often correlate with instability |
| `search_code` | `repo`, `query`, `max_results` (default 10) | Matching files, paths, and highlighted snippets | Find where something is implemented without cloning the repo |
| `get_workflow_runs` | `repo`, `branch` (optional), `status` (optional), `limit` (default 10) | Recent GitHub Actions runs: status, conclusion, branch, link | "Is CI green" / "what's failing on main" |

Two tools do real computation rather than passing through a single API response:

- **`flag_stale_prs`** derives "days since last activity" from each open PR's `updated_at` timestamp and ranks by staleness. Logic in `compute_stale_prs()` (`src/tools/pull_requests.py`), independently tested in `tests/test_staleness_logic.py`.
- **`get_file_churn`** aggregates file-touch counts across a window of commit history - something no single GitHub endpoint returns. Logic in `compute_file_churn()` (`src/tools/commits.py`), tested in `tests/test_commits.py`.

All seven tools are strictly read-only. `src/github_client.py` only exposes HTTP GET helpers - there is no code path anywhere in this package that issues a POST, PATCH, PUT, or DELETE request against GitHub.

---

## Local setup (single-user, stdio)

### Install

```bash
git clone https://github.com/fatmah308/repolens.git
cd repolens
pip install -e ".[dev]"

# or, without building the package:
pip install -r requirements.txt
python src/server.py
```

Or once published: `pipx run repolens` / `pip install repolens`.

### GitHub token (recommended, not required)

RepoLens works without authentication, but GitHub rate-limits unauthenticated REST requests to 60/hour vs 5,000/hour authenticated. Set a [personal access token](https://github.com/settings/tokens):

```bash
cp .env.example .env
# edit .env: GITHUB_TOKEN=ghp_your_token_here
```

`src/config.py` loads `.env` automatically via `python-dotenv` (never overriding a real environment variable that's already set). A read-only, fine-grained token is sufficient - RepoLens never writes to GitHub.

### Connecting to Claude Desktop

- macOS config: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows config: `%APPDATA%\Claude\claude_desktop_config.json` (or, for some MSIX/packaged installs, under `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\` - use Claude Desktop's own Settings → Developer → "Edit config" button to find the exact file it reads on your machine)

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

---

## Hosted deployment (multi-tenant, HTTP + GitHub OAuth)

Everything below is for running RepoLens as a **shared service** that other people connect to with their own GitHub identity, instead of a token you'd have to hand out. It's a genuinely different deployment shape from local mode - more moving parts, and worth doing only if you actually want other people using it.

### How auth works

RepoLens implements the OAuth 2.0 authorization code grant against a GitHub OAuth App:

1. A person visits `{PUBLIC_URL}/auth/login` in a browser.
2. They're redirected to GitHub's consent screen and approve access.
3. GitHub redirects back to `{PUBLIC_URL}/auth/callback`, which exchanges the code for a GitHub access token, looks up their username, and issues RepoLens's own opaque **session token**.
4. They copy that session token into their MCP client as an `Authorization: Bearer <token>` header.
5. Every tool call carrying that header runs against **their own** GitHub identity and permissions - not a shared credential.

Session tokens are stored server-side (SQLite by default) and expire automatically after 30 days. The GitHub OAuth flow is a confidential, server-side exchange - the client secret never reaches a browser.

**A real limitation worth knowing**: classic GitHub OAuth Apps don't have a "read-only" scope the way fine-grained personal access tokens do. The default (`GITHUB_OAUTH_SCOPES=""`) grants access to public data only - enough for public repos, and the safest default for a multi-tenant server. Getting private-repo access requires requesting the `repo` scope, which also grants write access at the GitHub API level (RepoLens itself still never calls anything but GET, but a leaked session token would carry that broader permission). Decide deliberately before turning this on.

### 1. Create a GitHub OAuth App

Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App** (or your organization's equivalent):

- **Homepage URL**: your `PUBLIC_URL`, e.g. `https://repolens.example.com`
- **Authorization callback URL**: `{PUBLIC_URL}/auth/callback`, e.g. `https://repolens.example.com/auth/callback`

Save the **Client ID** and generate a **Client Secret**.

### 2. Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `REPOLENS_TRANSPORT` | Yes | Set to `http` to enable hosted mode |
| `REPOLENS_PUBLIC_URL` | Yes | The public URL people reach this at, e.g. `https://repolens.example.com`. Used to build the OAuth callback URL **and** to allow-list the host against DNS-rebinding protection - get this wrong and everything silently 4xxs |
| `GITHUB_OAUTH_CLIENT_ID` | Yes | From step 1 |
| `GITHUB_OAUTH_CLIENT_SECRET` | Yes | From step 1 - treat as a secret, never commit it |
| `REPOLENS_HOST` | No | Bind address (default `0.0.0.0`) |
| `REPOLENS_PORT` | No | Bind port (default `8000`) |
| `REPOLENS_SESSION_DB_PATH` | No | Where session data lives (default `repolens_sessions.db` in the working directory) - point this at a persistent volume, or restarts wipe everyone's login |
| `GITHUB_OAUTH_SCOPES` | No | Empty by default (public-repo access only); set to `repo` for private-repo access - see the limitation above |
| `REPOLENS_ALLOWED_HOSTS` / `REPOLENS_ALLOWED_ORIGINS` | No | Comma-separated extra hosts/origins to allow, if you sit behind a proxy/CDN presenting a different `Host` header than `PUBLIC_URL` |
| `GITHUB_TOKEN` | No | An operator-configured *fallback* token used only for requests with no `Authorization` header at all - fine for a small trusted internal deployment, otherwise leave unset so unauthenticated callers get a clear "please log in" error instead of silently using a shared identity |

### 3. Deploy

RepoLens ships a `Dockerfile` and is otherwise a plain Python package - deploy it however suits you (Railway, Render, Fly.io, a bare VM, Kubernetes, etc.).

```bash
docker build -t repolens .
docker run -p 8000:8000 \
  -e REPOLENS_TRANSPORT=http \
  -e REPOLENS_PUBLIC_URL=https://repolens.example.com \
  -e GITHUB_OAUTH_CLIENT_ID=your_client_id \
  -e GITHUB_OAUTH_CLIENT_SECRET=your_client_secret \
  -v repolens-data:/data \
  repolens
```

The image already sets `REPOLENS_SESSION_DB_PATH=/data/repolens_sessions.db` and mounts `/data` as a volume, so session data survives restarts as long as you attach a persistent volume there. Put a real TLS-terminating reverse proxy or your platform's load balancer in front of it - RepoLens itself speaks plain HTTP.

Health check endpoint: `GET /health` → `ok`.

### 4. Verify the deployment actually works

`/health` returning `ok` only confirms the container is running - it says nothing about whether OAuth, session storage, or the tools themselves work. Check those explicitly before handing the URL to anyone else:

**a. Test the OAuth login round-trip (browser):**

Visit `{PUBLIC_URL}/auth/login`. You should be redirected to GitHub's consent screen, and after approving, land back on a page reading "Connected as @your-username" with a session token in a box. Copy that token - you'll need it next.

If this fails, the error message is usually specific enough to act on directly: "OAuth is not configured" means `GITHUB_OAUTH_CLIENT_ID`/`SECRET` didn't actually get set (check for typos or a missed redeploy after setting them); a GitHub-side "redirect_uri mismatch" error means the callback URL registered on your OAuth App doesn't exactly match `{PUBLIC_URL}/auth/callback`.

**b. Test an authenticated tool call**, using [MCP Inspector](https://github.com/modelcontextprotocol/inspector), the official tool for exactly this:

```bash
npx @modelcontextprotocol/inspector
```

In the UI it opens: set transport to **Streamable HTTP**, URL to `{PUBLIC_URL}/mcp`, add header `Authorization: Bearer <session token from step a>`, and connect. All seven tools should be listed - try calling `get_open_issues` with `repo: "octocat/Hello-World"` and confirm real data comes back.

**c. Test that invalid sessions are actually rejected**, not just that valid ones work. Repeat (b) with a bogus token (`Authorization: Bearer not-a-real-token`) - you should get a clear "please log in again" error, not a silent failure, a crash, or (worst case) a result at all. This confirms the per-user auth check is really gating access rather than falling through to some default.

Only once (a)-(c) all check out is the deployment actually ready to hand to someone else.

### 5. Connect a client

Each person:

1. Visits `https://repolens.example.com/auth/login`, signs in to GitHub, and approves access.
2. Copies the session token shown on the resulting page.
3. Adds RepoLens as a **remote/HTTP** MCP connector in their client, pointed at `https://repolens.example.com/mcp`, with header `Authorization: Bearer <their session token>`.

(Exact connector-setup steps vary by client and MCP client support for custom HTTP headers on remote servers is still evolving - check your specific client's docs for how it exposes that option.)

### A note on scaling beyond one instance

`session_store.py` uses SQLite, which is fine for a single running instance. If you run multiple instances behind a load balancer, either point `REPOLENS_SESSION_DB_PATH` at a shared network volume, or swap the small set of functions in `session_store.py` for a shared backend (Redis, Postgres) - that module is the entire interface the rest of the app relies on, so it's a contained change.

---

## Development

```bash
pip install -e ".[dev]"

# Run tests (no real network calls anywhere - GitHub responses are mocked
# with respx, and hosted-mode tests use temp SQLite files)
pytest

# Lint
ruff check src tests
```

## Project layout

```
repolens/
│
├── src/
│   ├── server.py             ← MCP server entry point, registers tools, dual transport
│   ├── config.py              ← Loads .env; local + hosted-mode settings
│   ├── github_client.py       ← Thin read-only wrapper over GitHub REST API
│   ├── session_store.py       ← SQLite session tokens + OAuth CSRF state (hosted mode)
│   ├── oauth.py                ← GitHub OAuth login/callback handlers (hosted mode)
│   ├── _dates.py               ← Shared timestamp parsing helper
│   └── tools/
│       ├── __init__.py
│       ├── issues.py           ← get_open_issues
│       ├── pull_requests.py    ← get_pr_diff, flag_stale_prs (+ compute_stale_prs)
│       ├── commits.py          ← get_commit_history, get_file_churn (+ compute_file_churn)
│       ├── code_search.py      ← search_code
│       └── actions.py          ← get_workflow_runs
│
├── tests/
│   ├── conftest.py             ← shared fixtures, JSON fixture loader, isolated session DB
│   ├── fixtures/                ← mocked GitHub API JSON responses
│   ├── test_issues.py
│   ├── test_pull_requests.py
│   ├── test_commits.py
│   ├── test_staleness_logic.py  ← pure logic tests for flag_stale_prs, deterministic
│   ├── test_code_search.py
│   ├── test_actions.py
│   ├── test_session_store.py    ← pure logic tests for session/state expiry, no network
│   └── test_oauth.py             ← OAuth handler tests, GitHub side mocked
│
├── pyproject.toml              ← package metadata, enables `pip install` / `pipx run`
├── requirements.txt
├── Dockerfile                  ← hosted-mode deployment
├── .dockerignore
├── .env.example
├── .gitignore
├── README.md
│
└── .github/workflows/
    └── ci.yml                  ← lint + test on every push
```

Every tool module keeps a strict split: an `async` fetch function that talks to GitHub, plus, where there's real logic, a plain synchronous function that takes already-fetched data and returns the computed result. Tests exercise both layers - the async layer via `respx`-mocked HTTP (no real network calls anywhere in the suite), and the pure functions directly and deterministically.

### A note on the `src/` layout

`src/` is *flat* - `server.py`, `config.py`, etc. sit directly inside it rather than inside a nested `src/repolens/` folder. `pyproject.toml` maps this to the installed package name via `[tool.setuptools] package-dir`, so `pip install .` (and `pip install -e .`) both produce a normal, importable `repolens` package and a working `repolens` console script.

## License

MIT
