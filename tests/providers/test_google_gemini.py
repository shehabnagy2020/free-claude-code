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


@pytest.mark.asyncio
async def test_process_tool_call_none_index(provider_config):
    """Test handling of None index in tool calls."""
    from core.anthropic.sse import SSEBuilder

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GoogleGeminiProvider(provider_config)
        sse = SSEBuilder("msg_1", "model_1")

        # Tool call with index: None
        tc_info = {
            "index": None,
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": "{}"},
        }

        # Should not raise TypeError
        events = list(provider._process_tool_call(tc_info, sse))

        # Verify it started a tool block
        assert any("content_block_start" in e for e in events)
        assert 0 in sse.blocks.tool_states
        assert sse.blocks.tool_states[0].tool_id == "call_1"


@pytest.mark.asyncio
async def test_tool_name_sanitization(provider_config):
    """Test that tool names are sanitized for Gemini and un-sanitized in response."""
    from providers.google_gemini.request import build_request_body

    class MockTool:
        def __init__(self, name):
            self.name = name
            self.description = "test"
            self.input_schema = {"type": "object", "properties": {"a": {"type": "string"}}}

    class MockMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    class MockRequest:
        def __init__(self):
            self.model = "gemini-2.0-flash"
            self.messages = [MockMessage("user", "hello")]
            self.system = None
            self.tools = [MockTool("complex:tool:name")]
            self.tool_choice = None

    # 1. Test request sanitization
    request = MockRequest()
    body = build_request_body(request, thinking_enabled=False)

    sanitized_name = "complex_tool_name"
    assert body["tools"][0]["function"]["name"] == sanitized_name

    # 2. Test response un-sanitization
    from core.anthropic.sse import SSEBuilder

    with patch("providers.openai_compat.AsyncOpenAI"):
        provider = GoogleGeminiProvider(provider_config)
        sse = SSEBuilder("msg_1", "model_1")

        # Mock tool call from Gemini using sanitized name
        tc_info = {
            "index": 0,
            "id": "call_1",
            "function": {"name": sanitized_name, "arguments": "{}"},
        }

        events = list(provider._process_tool_call(tc_info, sse))

        # Check if the event contains the original name
        # We need to find the content_block_start event
        start_event = next(e for e in events if "content_block_start" in e)
        assert '"name": "complex:tool:name"' in start_event
