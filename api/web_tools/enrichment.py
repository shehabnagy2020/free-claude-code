"""Enrich empty WebSearch / WebFetch tool_results with Tavily data.

When Claude Code executes WebSearch itself (e.g. via DuckDuckGo) and returns
an empty tool_result, we intercept the *incoming* request (before forwarding to
the model) and replace the empty content with real Tavily search results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.models.anthropic import Message, MessagesRequest

from . import tavily as _tavily
from .streaming import _search_summary

_AGENT_WEB_SEARCH_NAMES = frozenset({"WebSearch", "web_search"})
_AGENT_WEB_FETCH_NAMES = frozenset({"WebFetch", "web_fetch"})
_EMPTY_THRESHOLD = 80  # chars — results shorter than this are treated as empty


def _is_empty_result(content: Any) -> bool:
    """True when a tool_result content is effectively empty or too short to be useful."""
    if content is None:
        return True
    if isinstance(content, str):
        stripped = content.strip()
        # Treat as empty if blank, or only contains "no results" type messages
        if not stripped or len(stripped) < _EMPTY_THRESHOLD:
            return True
        low = stripped.lower()
        return (
            "0 searches" in low
            or "no results" in low
            or "no web results" in low
            or "did 0" in low
        )
    if isinstance(content, list):
        if not content:
            return True
        # Flatten text out of content blocks
        text = " ".join(
            b.get("text", "") if isinstance(b, dict) else (b.text if hasattr(b, "text") else str(b))
            for b in content
        )
        stripped = text.strip()
        if len(stripped) < _EMPTY_THRESHOLD:
            return True
        low = stripped.lower()
        return "0 searches" in low or "no results" in low or "did 0" in low
    return False


def _build_tool_use_index(messages: list[Message]) -> dict[str, dict[str, Any]]:
    """Return a map of tool_use_id → {name, input} from all assistant messages."""
    index: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.role != "assistant":
            continue
        content = msg.content
        if isinstance(content, list):
            for block in content:
                btype = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
                if btype == "tool_use":
                    tid = getattr(block, "id", None) if not isinstance(block, dict) else block.get("id")
                    name = getattr(block, "name", None) if not isinstance(block, dict) else block.get("name")
                    inp = getattr(block, "input", {}) if not isinstance(block, dict) else block.get("input", {})
                    if tid:
                        index[tid] = {"name": name or "", "input": inp or {}}
    return index


async def enrich_empty_tool_results(
    request: MessagesRequest,
    *,
    tavily_api_key: str = "",
) -> MessagesRequest:
    """Return an updated request where empty WebSearch/WebFetch tool_results are filled with Tavily data.

    This is a no-op if no empty results are found or if tavily_api_key is unset.
    """
    if not tavily_api_key or not request.messages:
        return request

    tool_use_index = _build_tool_use_index(request.messages)
    if not tool_use_index:
        return request

    # Check last user message for tool_result blocks with empty content.
    last_msg = request.messages[-1]
    if last_msg.role != "user":
        return request
    if not isinstance(last_msg.content, list):
        return request

    enrichments: dict[int, str] = {}  # block index → new text content

    for i, block in enumerate(last_msg.content):
        btype = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
        if btype != "tool_result":
            continue
        tool_use_id = getattr(block, "tool_use_id", None) if not isinstance(block, dict) else block.get("tool_use_id")
        content = getattr(block, "content", None) if not isinstance(block, dict) else block.get("content")

        is_empty = _is_empty_result(content)
        tool_info = tool_use_index.get(tool_use_id) if tool_use_id else None
        tool_name_for_block = tool_info["name"] if tool_info else ""
        always_replace = tool_name_for_block in (_AGENT_WEB_SEARCH_NAMES | _AGENT_WEB_FETCH_NAMES)
        if not tool_use_id or not tool_info:
            continue
        if not is_empty and not always_replace:
            continue

        name: str = tool_info["name"]
        inp: dict[str, Any] = tool_info["input"]

        if name in _AGENT_WEB_SEARCH_NAMES:
            query: str = str(inp.get("query", inp.get("q", "")))
            if not query:
                continue
            # Append current year if no year-like token present — improves relevance.
            _year = str(datetime.now(UTC).year)
            if _year not in query:
                query = f"{query} {_year}"
            logger.info("enrichment: replacing WebSearch result with Tavily query={!r}", query)
            try:
                results = await _tavily.tavily_search(tavily_api_key, query)
                enrichments[i] = _search_summary(query, results)
                logger.info("enrichment: Tavily returned {} results for {!r}", len(results), query)
            except Exception as exc:
                logger.warning("enrichment: tavily_search failed: {}", exc)

        elif name in _AGENT_WEB_FETCH_NAMES:
            url: str = str(inp.get("url", ""))
            if not url:
                continue
            logger.info("enrichment: replacing WebFetch result with Tavily url={!r}", url)
            try:
                fetched = await _tavily.tavily_fetch(tavily_api_key, url)
                enrichments[i] = fetched.get("data", "")[:2000]
                logger.info("enrichment: Tavily fetched {} chars from {!r}", len(enrichments[i]), url)
            except Exception as exc:
                logger.warning("enrichment: tavily_fetch failed: {}", exc)

    if not enrichments:
        return request

    # Rebuild the last message with enriched content.
    # Serialize to dicts so we can safely mutate and re-validate.
    msg_dict = last_msg.model_dump()
    for idx, new_text in enrichments.items():
        msg_dict["content"][idx]["content"] = new_text

    new_messages = list(request.messages)
    new_messages[-1] = Message.model_validate(msg_dict)

    return request.model_copy(update={"messages": new_messages})
