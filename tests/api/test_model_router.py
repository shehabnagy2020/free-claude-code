from unittest.mock import patch

import pytest

from api.model_router import ModelRouter
from api.models.anthropic import Message, MessagesRequest, TokenCountRequest
from config.settings import Settings


@pytest.fixture
def settings():
    settings = Settings()
    settings.model = "nvidia_nim/fallback-model"
    settings.enable_model_thinking = True
    return settings


def test_model_router_resolves_default_model(settings):
    resolved = ModelRouter(settings).resolve("unknown-model")

    assert resolved.original_model == "unknown-model"
    assert resolved.provider_id == "nvidia_nim"
    assert resolved.provider_model == "fallback-model"
    assert resolved.provider_model_ref == "nvidia_nim/fallback-model"
    assert resolved.thinking_enabled is True


def test_model_router_resolves_custom_model(settings, monkeypatch):
    """Custom models are resolved by exact match on the model ref."""
    monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()
    s.model = "nvidia_nim/fallback-model"

    router = ModelRouter(s)
    resolved = router.resolve("ollama/glm-5.1:cloud")

    assert resolved.original_model == "ollama/glm-5.1:cloud"
    assert resolved.provider_id == "ollama"
    assert resolved.provider_model == "glm-5.1:cloud"
    assert resolved.provider_model_ref == "ollama/glm-5.1:cloud"


def test_model_router_resolves_gateway_model_id(settings, monkeypatch):
    """Gateway-prefixed model IDs (anthropic/...) route to the correct provider."""
    monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()

    router = ModelRouter(s)
    resolved = router.resolve("anthropic/ollama/glm-5.1:cloud")

    assert resolved.original_model == "anthropic/ollama/glm-5.1:cloud"
    assert resolved.provider_id == "ollama"
    assert resolved.provider_model == "glm-5.1:cloud"
    assert resolved.provider_model_ref == "ollama/glm-5.1:cloud"
    assert resolved.thinking_enabled is True


def test_model_router_resolves_no_thinking_gateway_model_id(settings, monkeypatch):
    """No-thinking gateway model IDs route correctly and disable thinking."""
    monkeypatch.setenv("MODEL_1", "nvidia_nim/z-ai/glm4.7")
    monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "true")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()

    router = ModelRouter(s)
    resolved = router.resolve("claude-3-freecc-no-thinking/nvidia_nim/z-ai/glm4.7")

    assert resolved.provider_id == "nvidia_nim"
    assert resolved.provider_model == "z-ai/glm4.7"
    assert resolved.thinking_enabled is False


def test_model_router_custom_model_request(settings, monkeypatch):
    """MessagesRequest with custom model routes correctly."""
    monkeypatch.setenv("MODEL_1", "open_router/deepseek/deepseek-r1")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()
    s.model = "nvidia_nim/fallback-model"

    request = MessagesRequest(
        model="open_router/deepseek/deepseek-r1",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
    )
    routed = ModelRouter(s).resolve_messages_request(request)

    assert routed.request.model == "deepseek/deepseek-r1"
    assert routed.resolved.provider_model_ref == "open_router/deepseek/deepseek-r1"
    assert routed.resolved.original_model == "open_router/deepseek/deepseek-r1"


def test_model_router_resolves_custom_thinking(settings, monkeypatch):
    """Per-model thinking toggle works for custom models."""
    monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
    monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "false")
    monkeypatch.setenv("MODEL_2", "nvidia_nim/z-ai/glm4.7")
    monkeypatch.setenv("ENABLE_MODEL_2_THINKING", "true")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()

    router = ModelRouter(s)
    assert router.resolve("ollama/glm-5.1:cloud").thinking_enabled is False
    assert router.resolve("nvidia_nim/z-ai/glm4.7").thinking_enabled is True
    # Unknown model falls back to global default
    assert router.resolve("unknown-model").thinking_enabled is True


def test_model_router_routes_token_count_request(settings, monkeypatch):
    """Token count requests route correctly for custom models."""
    monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    s = Settings()

    request = TokenCountRequest(
        model="ollama/glm-5.1:cloud",
        messages=[Message(role="user", content="hello")],
    )
    routed = ModelRouter(s).resolve_token_count_request(request)

    assert routed.request.model == "glm-5.1:cloud"
    assert request.model == "ollama/glm-5.1:cloud"


def test_model_router_fallback(settings):
    """Unknown model names fall back to settings.model."""
    router = ModelRouter(settings)
    resolved = router.resolve("claude-opus-4-20250514")

    assert resolved.original_model == "claude-opus-4-20250514"
    assert resolved.provider_model_ref == "nvidia_nim/fallback-model"


def test_model_router_logs_direct(settings, monkeypatch):
    """Direct provider model IDs are logged as MODEL DIRECT."""
    with patch("api.model_router.logger.info") as mock_log:
        ModelRouter(settings).resolve("anthropic/nvidia_nim/z-ai/glm4.7")

    mock_log.assert_called()
    args = mock_log.call_args[0]
    assert "MODEL DIRECT" in args[0]


def test_model_router_logs_mapping(settings):
    with patch("api.model_router.logger.info") as mock_log:
        ModelRouter(settings).resolve("unknown-model")

    mock_log.assert_called()
    args = mock_log.call_args[0]
    assert "MODEL MAPPING" in args[0]
    assert args[1] == "unknown-model"


def test_model_router_direct_provider_model(settings):
    """Direct provider-prefixed model IDs (without gateway prefix) route correctly."""
    router = ModelRouter(settings)
    resolved = router.resolve("nvidia_nim/fallback-model")

    assert resolved.provider_id == "nvidia_nim"
    assert resolved.provider_model == "fallback-model"


def test_model_router_gateway_unknown_provider(settings):
    """Gateway ID with unknown provider falls back to default model."""
    resolved = ModelRouter(settings).resolve("anthropic/unknown_provider/some-model")
    # Unknown provider → _direct_provider_model returns None → falls to resolve_model
    # resolve_model strips anthropic/ prefix → "unknown_provider/some-model" → unknown provider → default
    assert resolved.provider_model_ref == "nvidia_nim/fallback-model"


def test_model_router_gateway_known_provider_unlisted_model(settings):
    """Gateway ID with known provider but unlisted model routes directly."""
    resolved = ModelRouter(settings).resolve("anthropic/nvidia_nim/z-ai/glm4.7")
    # Known provider → _direct_provider_model returns (nvidia_nim, z-ai/glm4.7, None)
    assert resolved.provider_id == "nvidia_nim"
    assert resolved.provider_model == "z-ai/glm4.7"
