"""Request builder for Google Gemini provider."""

from typing import Any

from loguru import logger

from core.anthropic import (
    ReasoningReplayMode,
    build_base_request_body,
)
from core.anthropic.conversion import OpenAIConversionError
from providers.exceptions import InvalidRequestError


def build_request_body(
    request_data: Any, *, thinking_enabled: bool
) -> dict:
    """Build OpenAI-format request body from Anthropic request."""
    logger.debug(
        "GEMINI_REQUEST: conversion start model={} msgs={}",
        getattr(request_data, "model", "?"),
        len(getattr(request_data, "messages", [])),
    )
    try:
        # Gemini OpenAI endpoint doesn't support reasoning_content field yet,
        # so we use THINK_TAGS for replay to be safe.
        body = build_base_request_body(
            request_data,
            reasoning_replay=ReasoningReplayMode.THINK_TAGS
            if thinking_enabled
            else ReasoningReplayMode.DISABLED,
        )
    except OpenAIConversionError as exc:
        raise InvalidRequestError(str(exc)) from exc

    # Gemini specific: ensure max_tokens is set if possible
    # but build_base_request_body already handles it.

    logger.debug(
        "GEMINI_REQUEST: conversion done model={} msgs={} tools={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
    )
    return body
