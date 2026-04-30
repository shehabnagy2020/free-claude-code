"""Tavily REST API client for web_search and web_fetch.

Configure via TAVILY_API_KEY=tvly-...
"""

from __future__ import annotations

import httpx
from loguru import logger

from .constants import _MAX_FETCH_CHARS, _MAX_SEARCH_RESULTS, _REQUEST_TIMEOUT_S

_SEARCH_URL = "https://api.tavily.com/search"
_EXTRACT_URL = "https://api.tavily.com/extract"


async def tavily_search(api_key: str, query: str) -> list[dict[str, str]]:
    """Run a web search via Tavily REST API."""
    logger.debug("tavily_search query={!r}", query)
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": _MAX_SEARCH_RESULTS,
    }
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        response = await client.post(_SEARCH_URL, json=payload)
        response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    return [
        {
            "title": str(r.get("title", r.get("url", ""))),
            "url": str(r.get("url", "")),
            "snippet": str(r.get("content", r.get("description", ""))),
        }
        for r in results[:_MAX_SEARCH_RESULTS]
    ]


async def tavily_fetch(api_key: str, url: str) -> dict[str, str]:
    """Fetch and extract page content via Tavily REST API."""
    logger.debug("tavily_fetch url={!r}", url)
    payload = {"api_key": api_key, "urls": [url]}
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
        response = await client.post(_EXTRACT_URL, json=payload)
        response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    if results:
        r = results[0]
        return {
            "url": str(r.get("url", url)),
            "title": str(r.get("url", url)),
            "media_type": "text/plain",
            "data": str(r.get("raw_content", ""))[:_MAX_FETCH_CHARS],
        }
    return {"url": url, "title": url, "media_type": "text/plain", "data": ""}
