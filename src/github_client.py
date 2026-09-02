"""A thin, read-only async wrapper around the GitHub REST API.

This module intentionally exposes only HTTP GET helpers. RepoLens is a
read-only tool: nothing in this codebase issues POST/PATCH/PUT/DELETE
requests against GitHub, and no tool is permitted to add one.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import config


class GitHubAPIError(RuntimeError):
    """Raised when the GitHub API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API error ({status_code}): {message}")


class GitHubClient:
    """Minimal async GitHub REST API client, read-only by construction.

    Defaults come from ``repolens.config`` (in turn populated from real
    environment variables or a local ``.env`` file), but can be overridden
    per-instance - useful for tests and for pointing at GitHub Enterprise.
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.token = token if token is not None else config.GITHUB_TOKEN
        base_url = base_url if base_url is not None else config.GITHUB_API_BASE
        timeout = timeout if timeout is not None else config.REQUEST_TIMEOUT_SECONDS

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "repolens-mcp-server",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = await self._client.get(path, params=params, headers=headers)
        if response.status_code >= 400:
            message = response.text
            try:
                message = response.json().get("message", message)
            except ValueError:
                pass
            raise GitHubAPIError(response.status_code, message)
        return response

    async def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self._get(path, params=params, headers=headers)
        return response.json()

    async def get_text(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        response = await self._get(path, params=params, headers=headers)
        return response.text
