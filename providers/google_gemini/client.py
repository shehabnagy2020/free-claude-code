"""Google Gemini provider implementation."""

from typing import Any

from providers.base import ProviderConfig
from providers.openai_compat import OpenAIChatTransport

from .request import build_request_body

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
