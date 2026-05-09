from unittest.mock import AsyncMock, patch

import pytest

from config.provider_catalog import GOOGLE_GEMINI_DEFAULT_BASE
from providers.google_gemini import GoogleGeminiProvider


@pytest.fixture(autouse=True)
def mock_rate_limiter():
    """Mock the global rate limiter to prevent waiting."""
    with patch("providers.openai_compat.GlobalRateLimiter") as mock:
        instance = mock.get_scoped_instance.return_value
        instance.wait_if_blocked = AsyncMock(return_value=False)

        # execute_with_retry should call through to the actual function
        async def _passthrough(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        instance.execute_with_retry = AsyncMock(side_effect=_passthrough)
        yield instance


@pytest.mark.asyncio
async def test_init(provider_config):
    """Test Gemini provider initialization."""
    with patch("providers.openai_compat.AsyncOpenAI") as mock_openai:
        # Override base_url in config to use default if not provided
        provider_config.base_url = None
        provider = GoogleGeminiProvider(provider_config)
        assert provider._api_key == "test_key"
        assert provider._base_url == GOOGLE_GEMINI_DEFAULT_BASE
        mock_openai.assert_called_once()


@pytest.mark.asyncio
async def test_init_with_custom_base_url(provider_config):
    """Test Gemini provider initialization with custom base URL."""
    custom_url = "https://custom.gemini.api/v1"
    provider_config.base_url = custom_url
    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GoogleGeminiProvider(provider_config)
        assert provider._base_url == custom_url


@pytest.mark.asyncio
async def test_build_request_body_minimal():
    """Test building request body for Gemini."""
    from providers.google_gemini.request import build_request_body

    class MockMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    class MockRequest:
        def __init__(self):
            self.model = "gemini-2.0-flash"
            self.messages = [MockMessage("user", "hello")]
            self.system = None
            self.tools = None
            self.tool_choice = None

    request = MockRequest()
    body = build_request_body(request, thinking_enabled=False)

    assert body["model"] == "gemini-2.0-flash"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "hello"
