"""Tests for api/gateway_model_ids.py."""

from api.gateway_model_ids import (
    decode_gateway_model_id,
    gateway_model_id,
    no_thinking_gateway_model_id,
)


class TestGatewayModelId:
    """Test gateway model ID encoding."""

    def test_gateway_model_id_prefixes_with_anthropic(self):
        result = gateway_model_id("nvidia_nim/z-ai/glm4.7")
        assert result == "anthropic/nvidia_nim/z-ai/glm4.7"

    def test_gateway_model_id_with_nested_model(self):
        result = gateway_model_id("open_router/deepseek/deepseek-r1")
        assert result == "anthropic/open_router/deepseek/deepseek-r1"

    def test_gateway_model_id_with_ollama_model(self):
        result = gateway_model_id("ollama/glm-5.1:cloud")
        assert result == "anthropic/ollama/glm-5.1:cloud"


class TestNoThinkingGatewayModelId:
    """Test no-thinking gateway model ID encoding."""

    def test_no_thinking_prefixes_with_claude_3_freecc(self):
        result = no_thinking_gateway_model_id("nvidia_nim/z-ai/glm4.7")
        assert result == "claude-3-freecc-no-thinking/nvidia_nim/z-ai/glm4.7"

    def test_no_thinking_with_nested_model(self):
        result = no_thinking_gateway_model_id("open_router/deepseek/deepseek-r1")
        assert result == "claude-3-freecc-no-thinking/open_router/deepseek/deepseek-r1"


class TestDecodeGatewayModelId:
    """Test gateway model ID decoding."""

    def test_decode_anthropic_prefix(self):
        decoded = decode_gateway_model_id("anthropic/nvidia_nim/z-ai/glm4.7")
        assert decoded is not None
        assert decoded.provider_id == "nvidia_nim"
        assert decoded.provider_model == "z-ai/glm4.7"
        assert decoded.force_thinking_enabled is None

    def test_decode_no_thinking_prefix(self):
        decoded = decode_gateway_model_id(
            "claude-3-freecc-no-thinking/nvidia_nim/z-ai/glm4.7"
        )
        assert decoded is not None
        assert decoded.provider_id == "nvidia_nim"
        assert decoded.provider_model == "z-ai/glm4.7"
        assert decoded.force_thinking_enabled is False

    def test_decode_nested_model(self):
        decoded = decode_gateway_model_id("anthropic/open_router/deepseek/deepseek-r1")
        assert decoded is not None
        assert decoded.provider_id == "open_router"
        assert decoded.provider_model == "deepseek/deepseek-r1"

    def test_decode_unknown_prefix_returns_none(self):
        assert decode_gateway_model_id("unknown/model/name") is None

    def test_decode_no_slash_returns_none(self):
        assert decode_gateway_model_id("nvidia_nim") is None

    def test_decode_only_one_slash_after_prefix_returns_none(self):
        # "anthropic/nvidia_nim" has no model name after provider
        assert decode_gateway_model_id("anthropic/nvidia_nim") is None

    def test_decode_plain_provider_model_returns_none(self):
        # "nvidia_nim/z-ai/glm4.7" is not a gateway ID
        assert decode_gateway_model_id("nvidia_nim/z-ai/glm4.7") is None

    def test_decode_empty_string(self):
        assert decode_gateway_model_id("") is None

    def test_roundtrip_anthropic(self):
        """Encoding then decoding preserves the original ref."""
        ref = "nvidia_nim/z-ai/glm4.7"
        encoded = gateway_model_id(ref)
        decoded = decode_gateway_model_id(encoded)
        assert decoded is not None
        assert decoded.provider_id == "nvidia_nim"
        assert decoded.provider_model == "z-ai/glm4.7"

    def test_roundtrip_no_thinking(self):
        """No-thinking encoding then decoding returns force_thinking_enabled=False."""
        ref = "ollama/glm-5.1:cloud"
        encoded = no_thinking_gateway_model_id(ref)
        decoded = decode_gateway_model_id(encoded)
        assert decoded is not None
        assert decoded.force_thinking_enabled is False
        assert decoded.provider_id == "ollama"
        assert decoded.provider_model == "glm-5.1:cloud"
