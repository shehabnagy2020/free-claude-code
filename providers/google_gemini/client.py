"""Google Gemini provider implementation."""

from collections.abc import Iterator
from typing import Any

from core.anthropic import SSEBuilder
from providers.base import ProviderConfig
from providers.openai_compat import OpenAIChatTransport

from .request import GEMINI_TOOL_MAP, build_request_body

GOOGLE_GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


class GoogleGeminiProvider(OpenAIChatTransport):
    """Google Gemini provider using OpenAI-compatible endpoint."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="GoogleGemini",
            base_url=config.base_url or GOOGLE_GEMINI_DEFAULT_BASE,
            api_key=config.api_key,
        )

    def _build_request_body(
        self, request: Any, thinking_enabled: bool | None = None
    ) -> dict:
        return build_request_body(
            request,
            thinking_enabled=self._is_thinking_enabled(request, thinking_enabled),
        )

    def _process_tool_call(self, tc: dict, sse: SSEBuilder) -> Iterator[str]:
        """Un-sanitize tool names before emitting SSE events."""
        fn_delta = tc.get("function", {})
        incoming_name = fn_delta.get("name")
        if incoming_name:
            tool_map = GEMINI_TOOL_MAP.get()
            if incoming_name in tool_map:
                orig_name = tool_map[incoming_name]
                from loguru import logger

                logger.debug(
                    "GEMINI_RESPONSE: un-sanitizing tool name {} -> {}",
                    incoming_name,
                    orig_name,
                )
                fn_delta["name"] = orig_name

        return super()._process_tool_call(tc, sse)
