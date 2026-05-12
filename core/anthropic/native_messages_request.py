"""Native Anthropic Messages request body construction (JSON-ready dicts).

Provider adapters supply policy via parameters (defaults, OpenRouter post-steps).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

_REQUEST_FIELDS = (
    "model",
    "messages",
    "system",
    "max_tokens",
    "stop_sequences",
    "stream",
    "temperature",
    "top_p",
    "top_k",
    "metadata",
    "tools",
    "tool_choice",
    "thinking",
    "context_management",
    "output_config",
    "mcp_servers",
    "extra_body",
)

# Keys that would override routed canonical request fields if merged from ``extra_body``.
_OPENROUTER_EXTRA_BODY_FORBIDDEN_KEYS = frozenset(
    {
        "model",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "stream",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "metadata",
        "stop_sequences",
        "context_management",
        "output_config",
        "mcp_servers",
    }
)


class OpenRouterExtraBodyError(ValueError):
    """``extra_body`` contained reserved keys that would override canonical fields."""


def validate_openrouter_extra_body(extra: Any) -> None:
    """Reject ``extra_body`` keys that must not override routed request fields."""
    if not isinstance(extra, dict) or not extra:
        return
    bad = _OPENROUTER_EXTRA_BODY_FORBIDDEN_KEYS & extra.keys()
    if bad:
        raise OpenRouterExtraBodyError(
            f"extra_body must not override canonical request fields: {sorted(bad)}"
        )


_INTERNAL_FIELDS = {
    "thinking",
    "extra_body",
}


def _serialize_value(value: Any) -> Any:
    """Convert Pydantic models and lightweight objects into JSON-ready values."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {
            key: _serialize_value(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_serialize_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "__dict__"):
        return {
            key: _serialize_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return value


def _dump_request_fields(request_data: Any) -> dict[str, Any]:
    """Extract the public request fields (OpenRouter-style explicit field list)."""
    if isinstance(request_data, BaseModel):
        return request_data.model_dump(exclude_none=True)

    dumped: dict[str, Any] = {}
    for field in _REQUEST_FIELDS:
        value = getattr(request_data, field, None)
        if value is not None:
            dumped[field] = _serialize_value(value)
    return dumped


def dump_raw_messages_request(request_data: Any) -> dict[str, Any]:
    """Public JSON-ready dict of Anthropic public request fields (for native adapters)."""
    return _dump_request_fields(request_data)


def sanitize_native_messages_thinking_policy(
    messages: Any, *, thinking_enabled: bool
) -> Any:
    """Filter assistant message thinking blocks for upstream native Anthropic JSON.

    When ``thinking_enabled`` is false, remove ``thinking`` and ``redacted_thinking``
    history so disabled policy is not undermined by prior turns.

    When true, keep ``redacted_thinking`` and signed ``thinking``; remove only
    unsigned plain ``thinking`` blocks (not replayable).
    """
    if not isinstance(messages, list):
        return messages

    sanitized_messages: list[Any] = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        if message.get("role") != "assistant":
            sanitized_messages.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, list):
            sanitized_messages.append(message)
            continue

        if not thinking_enabled:
            sanitized_content = [
                block
                for block in content
                if not (
                    isinstance(block, dict)
                    and block.get("type") in ("thinking", "redacted_thinking")
                )
            ]
        else:
            sanitized_content = [
                block
                for block in content
                if not (
                    isinstance(block, dict)
                    and block.get("type") == "thinking"
                    and not isinstance(block.get("signature"), str)
                )
            ]

        sanitized_message = dict(message)
        sanitized_message["content"] = sanitized_content or ""
        sanitized_messages.append(sanitized_message)

    return sanitized_messages


_UNSUPPORTED_TOP_LEVEL_BLOCK_TYPES = frozenset({"document"})


def _convert_document_block(block: dict) -> dict:
    """Convert a ``document`` content block to a text description.

    Third-party Anthropic-compatible endpoints (Ollama, llama.cpp, LM Studio)
    do not support the ``document`` block type.  We preserve the information by
    converting it to a ``text`` block with a descriptive summary so the model
    still knows a document was present.
    """
    source = block.get("source", {})
    media_type = source.get("media_type", "application/octet-stream")
    # Base64 data is too large to include as text; provide metadata only.
    desc = f"[Document: {media_type}]"
    title = block.get("title") or block.get("name")
    if title:
        desc = f"[Document: {title} ({media_type})]"
    return {"type": "text", "text": desc}


def sanitize_native_messages_unsupported_blocks(messages: Any) -> Any:
    """Convert content block types not supported by upstream providers.

    Third-party Anthropic-compatible endpoints (Ollama, llama.cpp, LM Studio)
    do not support ``document`` blocks.  This function converts them to text
    descriptions so the model still knows a document was referenced, avoiding
    422 validation errors while preserving conversation context.
    """
    if not isinstance(messages, list):
        return messages

    changed = False
    sanitized_messages: list[Any] = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, list):
            sanitized_messages.append(message)
            continue

        new_content: list[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in _UNSUPPORTED_TOP_LEVEL_BLOCK_TYPES:
                changed = True
                new_content.append(_convert_document_block(block))
            else:
                new_content.append(block)

        # Also convert unsupported blocks nested inside tool_result content arrays
        for i, block in enumerate(new_content):
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("content"), list)
            ):
                nested: list[Any] = []
                nested_changed = False
                for sub in block["content"]:
                    if isinstance(sub, dict) and sub.get("type") in _UNSUPPORTED_TOP_LEVEL_BLOCK_TYPES:
                        nested.append(_convert_document_block(sub))
                        nested_changed = True
                    else:
                        nested.append(sub)
                if nested_changed:
                    new_content[i] = dict(block, content=nested if nested else "")

        if changed:
            sanitized_message = dict(message)
            sanitized_message["content"] = new_content if new_content else ""
            sanitized_messages.append(sanitized_message)
        else:
            sanitized_messages.append(message)

    if changed:
        from loguru import logger

        logger.info(
            "CONVERTED unsupported document blocks to text in {} message(s)",
            sum(
                1
                for m in sanitized_messages
                if isinstance(m, dict)
                and m is not messages
                and m not in messages
            ),
        )

    return sanitized_messages


def _normalize_system_prompt_for_openrouter(system: Any) -> Any:
    """Flatten Claude SDK system blocks for OpenRouter's native endpoint."""
    if not isinstance(system, list):
        return system

    text_parts: list[str] = []
    for block in system:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
    return "\n\n".join(text_parts).strip() if text_parts else system


def _apply_openrouter_reasoning_policy(body: dict[str, Any], thinking_cfg: Any) -> None:
    """Map Anthropic thinking controls onto OpenRouter reasoning controls."""
    reasoning = body.setdefault("reasoning", {"enabled": True})
    if not isinstance(reasoning, dict):
        return
    reasoning.setdefault("enabled", True)
    if not isinstance(thinking_cfg, dict):
        return
    budget_tokens = thinking_cfg.get("budget_tokens")
    if isinstance(budget_tokens, int):
        reasoning.setdefault("max_tokens", budget_tokens)


def build_base_native_anthropic_request_body(
    request: Any,
    *,
    default_max_tokens: int,
    thinking_enabled: bool,
) -> dict[str, Any]:
    """Serialize a Pydantic messages request to a generic native Anthropic body."""
    body = request.model_dump(exclude_none=True)

    body.pop("extra_body", None)

    if "thinking" in body:
        thinking_cfg = body.pop("thinking")
        if thinking_enabled and isinstance(thinking_cfg, dict):
            thinking_payload: dict[str, Any] = {"type": "enabled"}
            budget_tokens = thinking_cfg.get("budget_tokens")
            if isinstance(budget_tokens, int):
                thinking_payload["budget_tokens"] = budget_tokens
            body["thinking"] = thinking_payload

    if "max_tokens" not in body:
        body["max_tokens"] = default_max_tokens

    if "messages" in body:
        body["messages"] = sanitize_native_messages_thinking_policy(
            body["messages"],
            thinking_enabled=thinking_enabled,
        )
        body["messages"] = sanitize_native_messages_unsupported_blocks(
            body["messages"],
        )

    return body


def build_openrouter_native_request_body(
    request_data: Any,
    *,
    thinking_enabled: bool,
    default_max_tokens: int,
) -> dict[str, Any]:
    """Build an Anthropic-format request body for OpenRouter (policy hooks built-in)."""
    dumped_request = _dump_request_fields(request_data)
    request_extra = dumped_request.pop("extra_body", None)
    thinking_cfg = dumped_request.get("thinking")
    body: dict[str, Any] = {
        key: value
        for key, value in dumped_request.items()
        if key not in _INTERNAL_FIELDS
    }

    if isinstance(request_extra, dict):
        validate_openrouter_extra_body(request_extra)
        body.update(request_extra)

    body["messages"] = sanitize_native_messages_thinking_policy(
        body.get("messages"),
        thinking_enabled=thinking_enabled,
    )
    if "system" in body:
        body["system"] = _normalize_system_prompt_for_openrouter(body["system"])
    body["stream"] = True
    if body.get("max_tokens") is None:
        body["max_tokens"] = default_max_tokens

    if thinking_enabled:
        _apply_openrouter_reasoning_policy(body, thinking_cfg)

    return body
