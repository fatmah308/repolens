"""GitHub OAuth login flow for the hosted (streamable-http) server.

Implements the standard OAuth 2.0 authorization code grant against a
GitHub OAuth App (https://docs.github.com/en/apps/oauth-apps). This is a
server-side, confidential-client flow: the client secret never reaches
the browser, only this server holds it.

Flow:
    1. Browser hits GET /auth/login - we generate a CSRF ``state``, store
       it, and redirect to GitHub's authorize screen.
    2. The person approves access on GitHub.
    3. GitHub redirects back to GET /auth/callback?code=...&state=...
    4. We validate ``state`` (one-time use), exchange ``code`` for a
       GitHub access token, issue our own opaque session token, and show
       it so the person can paste it into their MCP client's connector
       config as an Authorization header.

These handlers are registered as custom routes on the FastMCP app in
server.py; they only run in hosted (http) mode.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from . import config, session_store


async def login(request: Request) -> RedirectResponse | PlainTextResponse:
    """GET /auth/login - start the GitHub OAuth flow."""
    if not config.GITHUB_OAUTH_CLIENT_ID:
        return PlainTextResponse(
            "OAuth is not configured on this server: GITHUB_OAUTH_CLIENT_ID is "
            "not set. See the README's hosted-deployment section.",
            status_code=500,
        )

    state = session_store.create_oauth_state()
    params = {
        "client_id": config.GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": config.oauth_callback_url(),
        "state": state,
    }
    if config.GITHUB_OAUTH_SCOPES:
        params["scope"] = config.GITHUB_OAUTH_SCOPES

    return RedirectResponse(f"{config.GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


async def callback(request: Request) -> HTMLResponse | PlainTextResponse:
    """GET /auth/callback - complete the flow and issue a session token."""
    error = request.query_params.get("error")
    if error:
        description = request.query_params.get("error_description", error)
        return PlainTextResponse(f"GitHub OAuth error: {description}", status_code=400)

    state = request.query_params.get("state")
    code = request.query_params.get("code")
    if not state or not code:
        return PlainTextResponse("Missing state or code parameter.", status_code=400)

    if not session_store.consume_oauth_state(state):
        return PlainTextResponse(
            "This login link is invalid or has expired. Please start over at "
            f"{config.oauth_login_url()}",
            status_code=400,
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            config.GITHUB_OAUTH_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.GITHUB_OAUTH_CLIENT_ID,
                "client_secret": config.GITHUB_OAUTH_CLIENT_SECRET,
                "code": code,
                "redirect_uri": config.oauth_callback_url(),
            },
        )
        token_data = token_response.json()
        github_token = token_data.get("access_token")
        if not github_token:
            error_desc = token_data.get("error_description", token_data)
            return PlainTextResponse(
                f"GitHub token exchange failed: {error_desc}", status_code=400
            )

        github_login = None
        user_response = await client.get(
            f"{config.GITHUB_API_BASE}/user",
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if user_response.status_code == 200:
            github_login = user_response.json().get("login")

    session_token = session_store.create_session(github_token, github_login)
    return HTMLResponse(_success_page(session_token, github_login))


def _success_page(session_token: str, github_login: str | None) -> str:
    who = f"@{github_login}" if github_login else "your GitHub account"
    return f"""<!DOCTYPE html>
<html>
<head>
<title>RepoLens - Connected</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 640px;
          margin: 60px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.5; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }}
  .token-box {{ background: #f4f4f4; padding: 16px; border-radius: 8px; margin: 20px 0;
                font-family: ui-monospace, monospace; word-break: break-all; font-size: 14px; }}
  .warn {{ color: #a15c00; font-size: 14px; }}
</style>
</head>
<body>
  <h2>Connected as {who}</h2>
  <p>Copy this session token into your MCP client's connector configuration
     as a bearer token header:</p>
  <div class="token-box">Authorization: Bearer {session_token}</div>
  <p class="warn">Treat this like a password - anyone with it can use your
     GitHub access through RepoLens. It expires automatically 30 days after
     being issued. You can safely close this page.</p>
</body>
</html>"""
