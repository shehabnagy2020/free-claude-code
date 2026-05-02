"""Tavily REST API client for web_search and web_fetch.

Configure via TAVILY_API_KEY=tvly-...
"""

from __future__ import annotations

import httpx
from loguru import logger

from .constants import _MAX_FETCH_CHARS, _MAX_SEARCH_RESULTS, _REQUEST_TIMEOUT_S

_SEARCH_URL = "https://api.tavily.com/search"
_EXTRACT_URL = "https://api.tavily.com/extract"

# Module-level client: reuses TCP connections and TLS sessions across calls.
# Eliminates ~300ms handshake overhead per request (significant on Pi 4).
_http_client = httpx.AsyncClient(
    timeout=_REQUEST_TIMEOUT_S,
    limits=httpx.Limits(
        max_keepalive_connections=5, max_connections=10, keepalive_expiry=30.0
    ),
)


async def tavily_search(api_key: str, query: str) -> list[dict[str, str]]:
    """Run a web search via Tavily REST API."""
    logger.debug("tavily_search query={!r}", query)
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": _MAX_SEARCH_RESULTS,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = await _http_client.post(_SEARCH_URL, json=payload, headers=headers)
    if response.status_code != 200:
        logger.warning(
            "tavily_search failed status={} body={!r}",
            response.status_code,
            response.text[:500],
        )
        response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    if not results:
        logger.warning("tavily_search returned 0 results for query={!r}", query)
    else:
        logger.info(
            "tavily_search returned {} results for query={!r}", len(results), query
        )
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
    payload = {"urls": [url]}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = await _http_client.post(_EXTRACT_URL, json=payload, headers=headers)
    if response.status_code != 200:
        logger.warning(
            "tavily_fetch failed status={} body={!r}",
            response.status_code,
            response.text[:500],
        )
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
