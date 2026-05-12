"""Request builder for Google Gemini provider."""

import re
from contextvars import ContextVar
from typing import Any

from loguru import logger

from core.anthropic import (
    ReasoningReplayMode,
    build_base_request_body,
)
from core.anthropic.conversion import OpenAIConversionError
from providers.exceptions import InvalidRequestError

# Map of sanitized_name -> original_name, used to un-sanitize in stream_response.
GEMINI_TOOL_MAP: ContextVar[dict[str, str]] = ContextVar("gemini_tool_map", default={})


def sanitize_gemini_name(name: str) -> str:
    """Sanitize name to [a-zA-Z0-9_-] and max 63 chars for Gemini."""
    if not name:
        return name
    # Replace non-allowed characters with underscores
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    # Truncate to 63 chars (Gemini limit)
    return safe[:63]


def build_request_body(request_data: Any, *, thinking_enabled: bool) -> dict:
    """Build OpenAI-format request body from Anthropic request."""
    logger.debug(
        "GEMINI_REQUEST: conversion start model={} msgs={}",
        getattr(request_data, "model", "?"),
        len(getattr(request_data, "messages", [])),
    )
    try:
        # Gemini 2.0 Thinking models REQUIRE an opaque "thought_signature" to link
        # tool calls to thoughts. Since we don't store these signatures from previous
        # responses, replaying history with 'reasoning_content' and tool calls
        # will ALWAYS fail with a 400 error.
        # The only workaround is to NOT show the model its past reasoning when
        # tool calls are involved, or simply disable reasoning replay entirely.
        body = build_base_request_body(
            request_data,
            reasoning_replay=ReasoningReplayMode.DISABLED,
        )
    except OpenAIConversionError as exc:
        raise InvalidRequestError(str(exc)) from exc

    # Gemini specific: OpenAI shim is strictly schema-bound and rejects unknown fields.
    # We must ensure we don't send anything it might reject.

    # 1. Gemini strictly forbids parameterless functions.
    if "tools" in body:
        for tool in body["tools"]:
            if tool.get("type") == "function":
                fn = tool.get("function", {})
                params = fn.get("parameters", {})
                if not params.get("properties"):
                    # Add a dummy parameter to avoid 400 Bad Request
                    fn["parameters"] = {
                        "type": "object",
                        "properties": {
                            "__gemini_dummy": {
                                "type": "string",
                                "description": "Unused dummy parameter to satisfy Gemini requirement.",
                            }
                        },
                    }

    # 2. Gemini OpenAI shim may reject "required" or object-based tool_choice.
    # Convert "required" to "auto" to be safe if it's not a specific function.
    if body.get("tool_choice") == "required":
        body["tool_choice"] = "auto"

    # 3. OpenAI shim is strictly schema-bound. We don't send parallel_tool_calls
    # to avoid potential "unknown field" errors in some shim versions.
    if "parallel_tool_calls" in body:
        del body["parallel_tool_calls"]

    # 4. Tool Name Sanitization: Gemini requires [a-zA-Z0-9_-] and max 63 chars.
    # Claude Code MCP tools often have colons and are very long.
    safe_to_orig: dict[str, str] = {}
    orig_to_safe: dict[str, str] = {}

    def _get_safe_name(orig_name: str) -> str:
        if orig_name in orig_to_safe:
            return orig_to_safe[orig_name]
        safe_name = sanitize_gemini_name(orig_name)
        # Ensure uniqueness
        base_safe = safe_name
        counter = 1
        while safe_name in safe_to_orig and safe_to_orig[safe_name] != orig_name:
            suffix = f"_{counter}"
            safe_name = base_safe[: 63 - len(suffix)] + suffix
            counter += 1
        safe_to_orig[safe_name] = orig_name
        orig_to_safe[orig_name] = safe_name
        return safe_name

    # Sanitize tools list
    if "tools" in body:
        for tool in body["tools"]:
            if tool.get("type") == "function":
                fn = tool["function"]
                fn["name"] = _get_safe_name(fn["name"])

    # Update tool_choice if it refers to a specific function
    tc = body.get("tool_choice")
    if isinstance(tc, dict) and tc.get("type") == "function":
        fn_choice = tc.get("function", {})
        if fn_choice.get("name"):
            fn_choice["name"] = _get_safe_name(fn_choice["name"])

    # Update all messages in history
    for msg in body.get("messages", []):
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                if fn.get("name"):
                    fn["name"] = _get_safe_name(fn["name"])
        if msg.get("role") == "tool" and msg.get("name"):
            msg["name"] = _get_safe_name(msg["name"])

        # Aggressively sanitize mentions of tools in text content (best effort)
        # This helps Gemini not hallucinate prefixes like 'default_api:'
        if isinstance(msg.get("content"), str):
            for orig, safe in orig_to_safe.items():
                if ":" in orig and orig in msg["content"]:
                    msg["content"] = msg["content"].replace(orig, safe)

    # Store the mapping for un-sanitizing in the response
    if safe_to_orig:
        GEMINI_TOOL_MAP.set(safe_to_orig)

    # 5. Gemini OpenAI shim: assistant messages with tool_calls should have content: None
    # instead of content: "" if no text is present.
    for msg in body.get("messages", []):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if not msg.get("content") or str(msg.get("content")).strip() == "":
                msg["content"] = None

    logger.info(
        "GEMINI_REQUEST: model={} msgs={} tools={} thinking_enabled={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
        thinking_enabled,
    )

    # Log summary of tools and history for debugging
    logger.info(
        "GEMINI_DEBUG: tools={}",
        [t["function"]["name"] for t in body.get("tools", []) if t.get("type") == "function"][:5],
    )
    if body.get("messages"):
        last_few = body["messages"][-3:]
        for i, m in enumerate(last_few):
            logger.info(
                "GEMINI_DEBUG: hist[-{}] role={} keys={} content_type={}",
                len(last_few) - i,
                m.get("role"),
                list(m.keys()),
                type(m.get("content")),
            )

    return body
