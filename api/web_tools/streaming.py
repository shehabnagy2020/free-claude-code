"""SSE streaming for local web_search / web_fetch server tool results."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.models.anthropic import MessagesRequest
from core.anthropic.server_tool_sse import (
    SERVER_TOOL_USE,
    WEB_FETCH_TOOL_ERROR,
    WEB_FETCH_TOOL_RESULT,
    WEB_SEARCH_TOOL_RESULT,
    WEB_SEARCH_TOOL_RESULT_ERROR,
)
from core.anthropic.sse import format_sse_event

from . import outbound
from . import tavily as _tavily
from .constants import _MAX_FETCH_CHARS
from .egress import WebFetchEgressPolicy
from .parsers import extract_query, extract_url
from .request import (
    forced_server_tool_name,
    forced_tool_turn_text,
    has_tool_named,
)

# Both Anthropic server tool names (lowercase) and Claude Code agent tool names (CamelCase)
_WEB_TOOL_NAMES = frozenset({"web_search", "web_fetch", "WebSearch", "WebFetch"})


def _search_summary(query: str, results: list[dict[str, str]]) -> str:
    today = datetime.now(UTC).strftime("%B %d, %Y")
    if not results:
        return f"No web search results found for: {query} (searched {today})"
    lines = [f"Web search results for: {query} (retrieved {today})"]
    for index, result in enumerate(results, start=1):
        snippet = result.get("snippet", "")
        entry = f"{index}. {result['title']}\n   {result['url']}"
        if snippet:
            entry += f"\n   {snippet}"
        lines.append(entry)
    return "\n\n".join(lines)


async def stream_web_server_tool_response(
    request: MessagesRequest,
    input_tokens: int,
    *,
    web_fetch_egress: WebFetchEgressPolicy,
    verbose_client_errors: bool = False,
    tavily_api_key: str = "",
) -> AsyncIterator[str]:
    """Stream a minimal Anthropic-shaped turn for forced `web_search` / `web_fetch` (local fallback).

    When `ENABLE_WEB_SERVER_TOOLS` is on, this is a proxy-side execution path — not a full
    hosted Anthropic citation or encrypted-content pipeline.
    """
    tool_name = forced_server_tool_name(request)
    if tool_name is None or not has_tool_named(request, tool_name):
        logger.warning(
            "stream_web_server_tool_response: no forced tool found, returning empty"
        )
        return

    text = forced_tool_turn_text(request)
    message_id = f"msg_{uuid.uuid4()}"
    tool_id = f"srvtoolu_{uuid.uuid4().hex}"
    usage_key = (
        "web_search_requests" if tool_name == "web_search" else "web_fetch_requests"
    )
    tool_input = (
        {"query": extract_query(text)}
        if tool_name == "web_search"
        else {"url": extract_url(text)}
    )
    _result_block_for_tool = {
        "web_search": WEB_SEARCH_TOOL_RESULT,
        "web_fetch": WEB_FETCH_TOOL_RESULT,
    }
    _error_payload_type_for_tool = {
        "web_search": WEB_SEARCH_TOOL_RESULT_ERROR,
        "web_fetch": WEB_FETCH_TOOL_ERROR,
    }

    yield format_sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": request.model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        },
    )
    yield format_sse_event(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": SERVER_TOOL_USE,
                "id": tool_id,
                "name": tool_name,
                "input": tool_input,
            },
        },
    )
    yield format_sse_event(
        "content_block_stop", {"type": "content_block_stop", "index": 0}
    )

    logger.info(
        "web_server_tool: tool={} input={!r} tavily_key_set={}",
        tool_name,
        tool_input,
        bool(tavily_api_key),
    )

    try:
        if tool_name == "web_search":
            query = str(tool_input["query"])
            if not tavily_api_key:
                raise RuntimeError(
                    "TAVILY_API_KEY is not configured. Set it in your .env to enable web search."
                )
            logger.info("tavily_search: calling API for query={!r}", query)
            results = await _tavily.tavily_search(tavily_api_key, query)
            logger.info("tavily_search: got {} results", len(results))
            result_content: Any = [
                {
                    "type": "web_search_result",
                    "title": result["title"],
                    "url": result["url"],
                }
                for result in results
            ]
            summary = _search_summary(query, results)
            result_block_type = WEB_SEARCH_TOOL_RESULT
        else:
            if not tavily_api_key:
                raise RuntimeError(
                    "TAVILY_API_KEY is not configured. Set it in your .env to enable web fetch."
                )
            logger.info(
                "tavily_fetch: calling API for url={!r}", str(tool_input.get("url", ""))
            )
            fetched = await _tavily.tavily_fetch(tavily_api_key, str(tool_input["url"]))
            result_content = {
                "type": "web_fetch_result",
                "url": fetched["url"],
                "content": {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": fetched["media_type"],
                        "data": fetched["data"],
                    },
                    "title": fetched["title"],
                    "citations": {"enabled": True},
                },
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
            summary = fetched["data"][:_MAX_FETCH_CHARS]
            result_block_type = WEB_FETCH_TOOL_RESULT
    except Exception as error:
        fetch_url = str(tool_input["url"]) if tool_name == "web_fetch" else None
        logger.error(
            "web_server_tool FAILED tool={} exc_type={} exc={}",
            tool_name,
            type(error).__name__,
            error,
        )
        outbound._log_web_tool_failure(tool_name, error, fetch_url=fetch_url)
        result_block_type = _result_block_for_tool[tool_name]
        result_content = {
            "type": _error_payload_type_for_tool[tool_name],
            "error_code": "unavailable",
        }
        summary = outbound._web_tool_client_error_summary(
            tool_name, error, verbose=verbose_client_errors
        )

    output_tokens = max(1, len(summary) // 4)

    yield format_sse_event(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": result_block_type,
                "tool_use_id": tool_id,
                "content": result_content,
            },
        },
    )
    yield format_sse_event(
        "content_block_stop", {"type": "content_block_stop", "index": 1}
    )
    # Model-facing summary: stream as normal text deltas (CLI/transcript code reads `text_delta`,
    # not eager `text` on `content_block_start`).
    yield format_sse_event(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 2,
            "content_block": {"type": "text", "text": ""},
        },
    )
    yield format_sse_event(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 2,
            "delta": {"type": "text_delta", "text": summary},
        },
    )
    yield format_sse_event(
        "content_block_stop", {"type": "content_block_stop", "index": 2}
    )
    yield format_sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "server_tool_use": {usage_key: 1},
            },
        },
    )
    yield format_sse_event("message_stop", {"type": "message_stop"})


# ---------------------------------------------------------------------------
# SSE parsing helper
# ---------------------------------------------------------------------------


def _parse_sse_event_string(sse_string: str) -> tuple[str, dict[str, Any]]:
    """Parse a formatted SSE event string into (event_type, data_dict)."""
    event_type = ""
    data_text = ""
    for line in sse_string.strip().split("\n"):
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_text = line.split(":", 1)[1].strip()
    if data_text:
        try:
            data = json.loads(data_text)
            return event_type, data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return event_type, {}
    return event_type, {}


# ---------------------------------------------------------------------------
# Tavily execution helper
# ---------------------------------------------------------------------------


async def _execute_tavily_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tavily_api_key: str,
    verbose_client_errors: bool = False,
) -> tuple[Any, str, str]:
    """Execute web_search or web_fetch via Tavily.

    Returns ``(result_content, summary_text, result_block_type)``.
    """
    try:
        if tool_name == "web_search":
            query = str(tool_input.get("query", ""))
            if not tavily_api_key:
                raise RuntimeError(
                    "TAVILY_API_KEY is not configured. Set it in your .env to enable web search."
                )
            results = await _tavily.tavily_search(tavily_api_key, query)
            result_content: Any = [
                {
                    "type": "web_search_result",
                    "title": result["title"],
                    "url": result["url"],
                }
                for result in results
            ]
            summary = _search_summary(query, results)
            return result_content, summary, WEB_SEARCH_TOOL_RESULT
        else:
            url = str(tool_input.get("url", ""))
            if not tavily_api_key:
                raise RuntimeError(
                    "TAVILY_API_KEY is not configured. Set it in your .env to enable web fetch."
                )
            fetched = await _tavily.tavily_fetch(tavily_api_key, url)
            result_content = {
                "type": "web_fetch_result",
                "url": fetched["url"],
                "content": {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": fetched["media_type"],
                        "data": fetched["data"],
                    },
                    "title": fetched["title"],
                    "citations": {"enabled": True},
                },
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
            summary = fetched["data"][:_MAX_FETCH_CHARS]
            return result_content, summary, WEB_FETCH_TOOL_RESULT
    except Exception as error:
        fetch_url = str(tool_input.get("url", "")) if tool_name == "web_fetch" else None
        outbound._log_web_tool_failure(tool_name, error, fetch_url=fetch_url)
        _error_types = {
            "web_search": WEB_SEARCH_TOOL_RESULT_ERROR,
            "web_fetch": WEB_FETCH_TOOL_ERROR,
        }
        _result_types = {
            "web_search": WEB_SEARCH_TOOL_RESULT,
            "web_fetch": WEB_FETCH_TOOL_RESULT,
        }
        result_content = {
            "type": _error_types[tool_name],
            "error_code": "unavailable",
        }
        summary = outbound._web_tool_client_error_summary(
            tool_name, error, verbose=verbose_client_errors
        )
        return result_content, summary, _result_types[tool_name]


# ---------------------------------------------------------------------------
# Stream interception: intercept model tool_use for web_search/web_fetch
# ---------------------------------------------------------------------------


async def stream_with_web_tool_interception(
    provider_stream: AsyncIterator[str],
    *,
    tavily_api_key: str = "",
    verbose_client_errors: bool = False,
) -> AsyncIterator[str]:
    """Wrap a provider SSE stream to intercept web_search/web_fetch tool_use calls.

    When the model generates a ``tool_use`` for ``web_search`` or ``web_fetch``,
    this function:

    1. Suppresses the original ``tool_use`` content block events.
    2. Executes the search / fetch via *Tavily*.
    3. Emits ``server_tool_use`` + ``web_search_tool_result`` (or
       ``web_fetch_tool_result``) + a text summary block in their place.
    4. Changes ``stop_reason`` from ``tool_use`` to ``end_turn``.

    Non-web-tool ``tool_use`` blocks and all other events pass through unchanged
    (with index adjustment when interception adds extra blocks).
    """
    # ---- state ----
    intercepting_index: int = -1  # block index currently being intercepted
    intercepting_tool_name: str = ""
    input_json_parts: list[str] = []
    index_offset: int = 0  # cumulative extra blocks inserted
    did_intercept: bool = False  # whether any tool_use was intercepted

    async for raw_event in provider_stream:
        event_type, data = _parse_sse_event_string(raw_event)

        # -- content_block_start -----------------------------------------
        if event_type == "content_block_start":
            block = data.get("content_block", {})
            if not isinstance(block, dict):
                yield raw_event
                continue

            block_type = block.get("type", "")
            block_name = block.get("name", "")
            original_index: int = data.get("index", 0)

            if block_type == "tool_use" and block_name in _WEB_TOOL_NAMES:
                intercepting_index = original_index
                intercepting_tool_name = block_name
                input_json_parts = []
                continue  # suppress

            if index_offset:
                data["index"] = original_index + index_offset
                yield format_sse_event(event_type, data)
            else:
                yield raw_event
            continue

        # -- content_block_delta -----------------------------------------
        if event_type == "content_block_delta":
            ev_index: int = data.get("index", -1)

            if ev_index == intercepting_index and intercepting_index >= 0:
                delta = data.get("delta", {})
                if isinstance(delta, dict) and delta.get("type") == "input_json_delta":
                    input_json_parts.append(str(delta.get("partial_json", "")))
                continue  # suppress

            if index_offset:
                data["index"] = ev_index + index_offset
                yield format_sse_event(event_type, data)
            else:
                yield raw_event
            continue

        # -- content_block_stop ------------------------------------------
        if event_type == "content_block_stop":
            ev_index = data.get("index", -1)

            if ev_index == intercepting_index and intercepting_index >= 0:
                # Assemble the full tool input from buffered JSON deltas.
                full_json_str = "".join(input_json_parts)
                tool_input: dict[str, Any] = (
                    json.loads(full_json_str) if full_json_str.strip() else {}
                )
                adj = intercepting_index + index_offset

                # CamelCase names (WebSearch/WebFetch) are Claude Code agent tools.
                # Normalize to lowercase for Tavily execution.
                _tavily_name = (
                    "web_search"
                    if intercepting_tool_name in ("WebSearch", "web_search")
                    else "web_fetch"
                )
                _is_agent_tool = (
                    bool(intercepting_tool_name) and intercepting_tool_name[0].isupper()
                )

                logger.info(
                    "web_tool_intercept: name={} tavily_name={} agent={} input={!r}",
                    intercepting_tool_name,
                    _tavily_name,
                    _is_agent_tool,
                    tool_input,
                )

                # Execute Tavily
                (
                    _result_content,
                    summary,
                    _result_block_type,
                ) = await _execute_tavily_tool(
                    _tavily_name,
                    tool_input,
                    tavily_api_key=tavily_api_key,
                    verbose_client_errors=verbose_client_errors,
                )

                if _is_agent_tool:
                    # For CamelCase agent tools: emit only a plain text block.
                    # Claude Code doesn't understand server_tool_use format.
                    # 1 original block → 1 text block  ⇒  offset unchanged
                    yield format_sse_event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": adj,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    yield format_sse_event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": adj,
                            "delta": {"type": "text_delta", "text": summary},
                        },
                    )
                    yield format_sse_event(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": adj},
                    )
                    # 1:1 replacement — no index_offset change
                else:
                    srv_tool_id = f"srvtoolu_{uuid.uuid4().hex}"
                    # Block A: server_tool_use
                    yield format_sse_event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": adj,
                            "content_block": {
                                "type": SERVER_TOOL_USE,
                                "id": srv_tool_id,
                                "name": intercepting_tool_name,
                                "input": tool_input,
                            },
                        },
                    )
                    yield format_sse_event(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": adj},
                    )

                    # Block B: web_search_tool_result / web_fetch_tool_result
                    yield format_sse_event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": adj + 1,
                            "content_block": {
                                "type": _result_block_type,
                                "tool_use_id": srv_tool_id,
                                "content": _result_content,
                            },
                        },
                    )
                    yield format_sse_event(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": adj + 1},
                    )

                    # Block C: text summary
                    yield format_sse_event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": adj + 2,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    yield format_sse_event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": adj + 2,
                            "delta": {"type": "text_delta", "text": summary},
                        },
                    )
                    yield format_sse_event(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": adj + 2},
                    )

                    # 1 original block → 3 emitted blocks  ⇒  offset +2
                    index_offset += 2

                intercepting_index = -1
                did_intercept = True
                continue

            if index_offset:
                data["index"] = ev_index + index_offset
                yield format_sse_event(event_type, data)
            else:
                yield raw_event
            continue

        # -- message_delta -----------------------------------------------
        if event_type == "message_delta" and did_intercept:
            delta = data.get("delta", {})
            if isinstance(delta, dict) and delta.get("stop_reason") == "tool_use":
                delta["stop_reason"] = "end_turn"
                data["delta"] = delta
                yield format_sse_event(event_type, data)
                continue

        # -- everything else passes through ------------------------------
        yield raw_event
