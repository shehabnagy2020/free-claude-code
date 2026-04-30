"""Tavily MCP client for web_search and web_fetch server tools.

Uses the Tavily MCP Streamable HTTP transport (JSON-RPC 2.0).
Configure via TAVILY_MCP_URL=https://mcp.tavily.com/mcp/?tavilyApiKey=...
"""

from __future__ import annotations

import json

import httpx
from loguru import logger

from .constants import _MAX_FETCH_CHARS, _MAX_SEARCH_RESULTS, _REQUEST_TIMEOUT_S

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


async def _mcp_call(mcp_url: str, tool_name: str, arguments: dict) -> dict:
    """Execute a single MCP tools/call and return the parsed result dict."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        response = await client.post(mcp_url, json=payload, headers=_HEADERS)
        response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Tavily MCP error: {data['error']}")
    result = data.get("result", {})
    # MCP result content is a list; extract the first text item
    content = result.get("content", [])
    text = next((item["text"] for item in content if item.get("type") == "text"), "")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"raw": text}


async def tavily_search(
    mcp_url: str, query: str
) -> list[dict[str, str]]:
    """Run a web search via Tavily MCP; returns list compatible with _run_web_search."""
    logger.debug("tavily_search query={!r}", query)
    data = await _mcp_call(
        mcp_url,
        "tavily-search",
        {
            "query": query,
            "search_depth": "basic",
            "max_results": _MAX_SEARCH_RESULTS,
        },
    )
    results = data.get("results", [])
    out: list[dict[str, str]] = []
    for r in results[:_MAX_SEARCH_RESULTS]:
        out.append(
            {
                "title": str(r.get("title", r.get("url", ""))),
                "url": str(r.get("url", "")),
                "snippet": str(r.get("content", r.get("description", ""))),
            }
        )
    return out


async def tavily_fetch(mcp_url: str, url: str) -> dict[str, str]:
    """Fetch and extract page content via Tavily MCP extract tool."""
    logger.debug("tavily_fetch url={!r}", url)
    data = await _mcp_call(
        mcp_url,
        "tavily-extract",
        {"urls": [url]},
    )
    results = data.get("results", [])
    if results:
        r = results[0]
        raw_content = str(r.get("raw_content", ""))
        return {
            "url": str(r.get("url", url)),
            "title": str(r.get("url", url)),
            "media_type": "text/plain",
            "data": raw_content[:_MAX_FETCH_CHARS],
        }
    # Fallback: return whatever we got as raw text
    raw = str(data.get("raw", ""))
    return {
        "url": url,
        "title": url,
        "media_type": "text/plain",
        "data": raw[:_MAX_FETCH_CHARS],
    }
