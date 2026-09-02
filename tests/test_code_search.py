from __future__ import annotations

import respx
from httpx import Response
from repolens.tools.code_search import search_code, summarize_code_search

from .conftest import load_fixture


@respx.mock
async def test_search_code_fetches_and_scopes_query(github_client):
    route = respx.get("https://api.github.com/search/code").mock(
        return_value=Response(200, json=load_fixture("code_search.json"))
    )

    result = await search_code(github_client, "octocat/hello-world", "parse_config")

    assert route.called
    request = route.calls.last.request
    assert request.url.params["q"] == "parse_config repo:octocat/hello-world"
    assert len(result) == 2
    assert result[0]["path"] == "src/pagination.py"
    assert result[0]["repository"] == "octocat/hello-world"


@respx.mock
async def test_search_code_requests_text_match_header(github_client):
    route = respx.get("https://api.github.com/search/code").mock(
        return_value=Response(200, json=load_fixture("code_search.json"))
    )

    await search_code(github_client, "octocat/hello-world", "parse_config")

    request = route.calls.last.request
    assert request.headers["accept"] == "application/vnd.github.v3.text-match+json"


@respx.mock
async def test_search_code_respects_max_results(github_client):
    respx.get("https://api.github.com/search/code").mock(
        return_value=Response(200, json=load_fixture("code_search.json"))
    )

    result = await search_code(
        github_client, "octocat/hello-world", "parse_config", max_results=1
    )

    assert len(result) == 1


def test_summarize_code_search_extracts_fragments():
    raw = load_fixture("code_search.json")

    result = summarize_code_search(raw)

    assert result[0]["fragments"] == [
        "def parse_config(path):\n    ...",
        "# TODO: parse_config edge cases",
    ]
    assert result[1]["fragments"] == ["class ConfigParser:"]


def test_summarize_code_search_handles_no_matches():
    raw = {"items": [{"path": "x.py", "repository": {"full_name": "o/r"}, "sha": "abc"}]}

    result = summarize_code_search(raw)

    assert result[0]["fragments"] == []


def test_summarize_code_search_empty_items():
    assert summarize_code_search({"items": []}) == []
    assert summarize_code_search({}) == []
