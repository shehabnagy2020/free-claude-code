"""Tests for config/settings.py and config/nim.py"""

import os

import pytest
from pydantic import ValidationError

from config.constants import (
    ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS,
    HTTP_CONNECT_TIMEOUT_DEFAULT,
)
from config.nim import NimSettings
from config.settings import Settings, provider_display


class TestSettings:
    """Test Settings configuration."""

    def test_settings_loads(self):
        """Ensure Settings can be instantiated."""

        settings = Settings()
        assert settings is not None

    def test_default_values(self, monkeypatch):
        """Test default values are set and have correct types."""

        monkeypatch.delenv("MODEL", raising=False)
        monkeypatch.delenv("HTTP_READ_TIMEOUT", raising=False)
        monkeypatch.delenv("HTTP_CONNECT_TIMEOUT", raising=False)
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.model == "nvidia_nim/z-ai/glm4.7"
        assert isinstance(settings.provider_rate_limit, int)
        assert isinstance(settings.provider_rate_window, int)
        assert isinstance(settings.nim.temperature, float)
        assert isinstance(settings.fast_prefix_detection, bool)
        assert isinstance(settings.enable_model_thinking, bool)
        assert settings.http_read_timeout == 300.0
        assert settings.http_connect_timeout == HTTP_CONNECT_TIMEOUT_DEFAULT
        assert settings.enable_web_server_tools is False
        assert settings.log_raw_api_payloads is False
        assert settings.log_raw_sse_events is False
        assert settings.debug_platform_edits is False
        assert settings.debug_subagent_stack is False

    def test_get_settings_cached(self):
        """Test get_settings returns cached instance."""
        from config.settings import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2  # Same object (cached)

    def test_empty_string_to_none_for_optional_int(self):
        """Test that empty string converts to None for optional string fields."""

        # Settings should handle NVIDIA_NIM_SEED="" gracefully
        settings = Settings()
        assert settings.nim.seed is None or isinstance(settings.nim.seed, int)

    def test_model_setting(self):
        """Test model setting exists and is a string."""

        settings = Settings()
        assert isinstance(settings.model, str)
        assert len(settings.model) > 0

    def test_base_url_constant(self):
        """Test NVIDIA_NIM_DEFAULT_BASE is a constant."""
        from providers.nvidia_nim import NVIDIA_NIM_DEFAULT_BASE

        assert NVIDIA_NIM_DEFAULT_BASE == "https://integrate.api.nvidia.com/v1"

    def test_lm_studio_base_url_from_env(self, monkeypatch):
        """LM_STUDIO_BASE_URL env var is loaded into settings."""

        monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://custom:5678/v1")
        settings = Settings()
        assert settings.lm_studio_base_url == "http://custom:5678/v1"

    def test_ollama_base_url_defaults_to_root(self, monkeypatch):
        """OLLAMA_BASE_URL defaults to the Anthropic-compatible Ollama root URL."""

        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.ollama_base_url == "http://localhost:11434"

    def test_ollama_base_url_rejects_v1_suffix(self, monkeypatch):
        """OLLAMA_BASE_URL must not include /v1 for native Anthropic messages."""

        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        with pytest.raises(ValidationError, match="without /v1"):
            Settings()

    def test_provider_rate_limit_from_env(self, monkeypatch):
        """PROVIDER_RATE_LIMIT env var is loaded into settings."""

        monkeypatch.setenv("PROVIDER_RATE_LIMIT", "20")
        settings = Settings()
        assert settings.provider_rate_limit == 20

    def test_provider_rate_window_from_env(self, monkeypatch):
        """PROVIDER_RATE_WINDOW env var is loaded into settings."""

        monkeypatch.setenv("PROVIDER_RATE_WINDOW", "30")
        settings = Settings()
        assert settings.provider_rate_window == 30

    def test_http_read_timeout_from_env(self, monkeypatch):
        """HTTP_READ_TIMEOUT env var is loaded into settings."""

        monkeypatch.setenv("HTTP_READ_TIMEOUT", "600")
        settings = Settings()
        assert settings.http_read_timeout == 600.0

    def test_http_write_timeout_from_env(self, monkeypatch):
        """HTTP_WRITE_TIMEOUT env var is loaded into settings."""

        monkeypatch.setenv("HTTP_WRITE_TIMEOUT", "20")
        settings = Settings()
        assert settings.http_write_timeout == 20.0

    def test_http_connect_timeout_from_env(self, monkeypatch):
        """HTTP_CONNECT_TIMEOUT env var is loaded into settings."""

        monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "5")
        settings = Settings()
        assert settings.http_connect_timeout == 5.0

    def test_http_connect_timeout_default_matches_shared_constant(
        self, monkeypatch
    ) -> None:
        """Default must match config.constants (and README / .env.example)."""

        monkeypatch.delenv("HTTP_CONNECT_TIMEOUT", raising=False)
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.http_connect_timeout == HTTP_CONNECT_TIMEOUT_DEFAULT
        assert HTTP_CONNECT_TIMEOUT_DEFAULT == 10.0

    def test_enable_model_thinking_from_env(self, monkeypatch):
        """ENABLE_MODEL_THINKING env var is loaded into settings."""

        monkeypatch.setenv("ENABLE_MODEL_THINKING", "false")
        settings = Settings()
        assert settings.enable_model_thinking is False

    def test_anthropic_auth_token_from_env_without_dotenv_key(self, monkeypatch):
        """ANTHROPIC_AUTH_TOKEN env var is loaded when dotenv does not define it."""

        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.anthropic_auth_token == "process-token"
        assert settings.uses_process_anthropic_auth_token() is True

    def test_empty_dotenv_anthropic_auth_token_overrides_process_env(
        self, monkeypatch, tmp_path
    ):
        """An explicit empty .env token disables auth despite stale shell tokens."""

        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_AUTH_TOKEN=\n", encoding="utf-8")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-client-token")
        monkeypatch.setitem(Settings.model_config, "env_file", (env_file,))

        settings = Settings()
        assert settings.anthropic_auth_token == ""
        assert settings.uses_process_anthropic_auth_token() is False

    def test_dotenv_anthropic_auth_token_overrides_process_env(
        self, monkeypatch, tmp_path
    ):
        """A configured .env token is the server token even with a stale shell token."""

        env_file = tmp_path / ".env"
        env_file.write_text(
            'ANTHROPIC_AUTH_TOKEN="server-token"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-client-token")
        monkeypatch.setitem(Settings.model_config, "env_file", (env_file,))

        settings = Settings()
        assert settings.anthropic_auth_token == "server-token"
        assert settings.uses_process_anthropic_auth_token() is False

    def test_removed_env_vars_raise(self, monkeypatch):
        """Removed env vars (MODEL_OPUS, ENABLE_THINKING, etc.) raise ValidationError."""

        for removed_key in (
            "MODEL_OPUS",
            "MODEL_SONNET",
            "MODEL_HAIKU",
            "ENABLE_OPUS_THINKING",
            "ENABLE_SONNET_THINKING",
            "ENABLE_HAIKU_THINKING",
            "NIM_ENABLE_THINKING",
            "ENABLE_THINKING",
        ):
            monkeypatch.setenv(removed_key, "test")
            with pytest.raises(ValidationError, match="removed"):
                Settings()
            monkeypatch.delenv(removed_key, raising=False)


# --- Custom Model Discovery Tests ---
class TestCustomModelDiscovery:
    """Test MODEL_N discovery and validation."""

    def test_no_custom_models_by_default(self, monkeypatch):
        """When no MODEL_N env vars, custom_models is empty."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        for key in list(os.environ.keys()):
            if key.startswith("MODEL_") and key != "MODEL" and key[6:].isdigit():
                monkeypatch.delenv(key, raising=False)

        settings = Settings()
        assert settings.custom_models == {}

    def test_custom_model_from_env(self, monkeypatch):
        """MODEL_1 env var is discovered as a custom model."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert "ollama/glm-5.1:cloud" in settings.custom_models
        entry = settings.custom_models["ollama/glm-5.1:cloud"]
        assert entry.model_ref == "ollama/glm-5.1:cloud"

    def test_custom_model_invalid_provider_raises(self, monkeypatch):
        """MODEL_N with invalid provider prefix raises ValidationError."""

        monkeypatch.setenv("MODEL_1", "bad_provider/some-model")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        with pytest.raises(ValidationError, match="Invalid provider"):
            Settings()

    def test_custom_model_no_slash_raises(self, monkeypatch):
        """MODEL_N without provider prefix raises ValidationError."""

        monkeypatch.setenv("MODEL_1", "noprefix")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        with pytest.raises(ValidationError, match="provider type"):
            Settings()

    def test_custom_model_empty_value_ignored(self, monkeypatch):
        """MODEL_N with empty value is ignored."""

        monkeypatch.setenv("MODEL_1", "")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.custom_models == {}

    def test_multiple_custom_models_ordered(self, monkeypatch):
        """Multiple MODEL_N entries are ordered by index."""

        monkeypatch.setenv("MODEL_2", "open_router/deepseek/deepseek-r1")
        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        keys = list(settings.custom_models.keys())
        assert keys[0] == "ollama/glm-5.1:cloud"
        assert keys[1] == "open_router/deepseek/deepseek-r1"

    def test_custom_model_thinking_override_true(self, monkeypatch):
        """ENABLE_MODEL_1_THINKING=true enables thinking for that model."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "true")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.custom_models["ollama/glm-5.1:cloud"].thinking_enabled is True

    def test_custom_model_thinking_override_false(self, monkeypatch):
        """ENABLE_MODEL_1_THINKING=false disables thinking for that model."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.custom_models["ollama/glm-5.1:cloud"].thinking_enabled is False

    def test_custom_model_thinking_inherits_default(self, monkeypatch):
        """Without ENABLE_MODEL_N_THINKING, thinking inherits ENABLE_MODEL_THINKING."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.custom_models["ollama/glm-5.1:cloud"].thinking_enabled is False

    def test_resolve_model_custom_exact_match(self, monkeypatch):
        """resolve_model returns exact match for custom models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.resolve_model("ollama/glm-5.1:cloud") == "ollama/glm-5.1:cloud"

    def test_resolve_model_gateway_anthropic_prefix(self, monkeypatch):
        """resolve_model strips 'anthropic/' prefix from gateway model IDs."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert (
            settings.resolve_model("anthropic/ollama/glm-5.1:cloud")
            == "ollama/glm-5.1:cloud"
        )

    def test_resolve_model_gateway_no_thinking_prefix(self, monkeypatch):
        """resolve_model strips 'claude-3-freecc-no-thinking/' prefix from gateway model IDs."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert (
            settings.resolve_model("claude-3-freecc-no-thinking/ollama/glm-5.1:cloud")
            == "ollama/glm-5.1:cloud"
        )

    def test_resolve_model_gateway_unknown_ref_with_known_provider(self, monkeypatch):
        """resolve_model with gateway prefix and known provider returns the ref."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        result = settings.resolve_model("anthropic/nvidia_nim/some-unknown-model")
        # Known provider → returns the ref even if not in custom_models
        assert result == "nvidia_nim/some-unknown-model"

    def test_resolve_model_gateway_unknown_provider_fallback(self, monkeypatch):
        """resolve_model with gateway prefix and unknown provider falls back."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        result = settings.resolve_model("anthropic/unknown_provider/some-model")
        # Unknown provider → falls back to default MODEL
        assert result == settings.model

    def test_resolve_model_custom_fallback(self, monkeypatch):
        """resolve_model falls back to default MODEL for unrecognized names."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.resolve_model("unknown-model") == settings.model

    def test_resolve_thinking_custom(self, monkeypatch):
        """resolve_thinking returns per-model thinking for custom models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.resolve_thinking("ollama/glm-5.1:cloud") is False

    def test_resolve_thinking_no_thinking_prefix_disables(self, monkeypatch):
        """resolve_thinking with claude-3-freecc-no-thinking prefix always returns False."""

        monkeypatch.setenv("MODEL_1", "nvidia_nim/z-ai/glm4.7")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "true")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert (
            settings.resolve_thinking(
                "claude-3-freecc-no-thinking/nvidia_nim/z-ai/glm4.7"
            )
            is False
        )

    def test_resolve_thinking_anthropic_prefix_inherits(self, monkeypatch):
        """resolve_thinking with anthropic/ prefix inherits per-model setting."""

        monkeypatch.setenv("MODEL_1", "nvidia_nim/z-ai/glm4.7")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "true")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.resolve_thinking("anthropic/nvidia_nim/z-ai/glm4.7") is True

    def test_resolve_thinking_fallback(self, monkeypatch):
        """resolve_thinking falls back to enable_model_thinking for unknown models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "true")
        monkeypatch.setenv("ENABLE_MODEL_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert settings.resolve_thinking("unknown-model") is False

    def test_get_models_list_custom(self, monkeypatch):
        """get_models_list returns custom models when configured."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("MODEL_2", "nvidia_nim/z-ai/glm4.7")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        models = settings.get_models_list()
        assert len(models) == 2
        assert models[0]["id"] == "ollama/glm-5.1:cloud"
        assert models[1]["id"] == "nvidia_nim/z-ai/glm4.7"

    def test_get_models_list_no_custom(self, monkeypatch):
        """get_models_list falls back to default model when no custom models."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        # Clear any MODEL_N env vars
        for key in list(os.environ.keys()):
            if key.startswith("MODEL_") and key != "MODEL" and key[6:].isdigit():
                monkeypatch.delenv(key, raising=False)
        settings = Settings()
        models = settings.get_models_list()
        assert len(models) == 1
        assert models[0]["id"] == settings.model

    def test_custom_model_from_dotenv(self, tmp_path, monkeypatch):
        """MODEL_N entries in .env files are discovered."""

        env_file = tmp_path / ".env"
        env_file.write_text('MODEL_1="ollama/glm-5.1:cloud"\n', encoding="utf-8")
        monkeypatch.setitem(Settings.model_config, "env_file", (env_file,))
        settings = Settings()
        assert "ollama/glm-5.1:cloud" in settings.custom_models

    def test_custom_model_duplicate_ref_deduplicates(self, monkeypatch):
        """MODEL_1 and MODEL_2 with same ref appear once in custom_models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("MODEL_2", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        settings = Settings()
        assert len(settings.custom_models) == 1
        assert "ollama/glm-5.1:cloud" in settings.custom_models


# --- NimSettings Validation Tests ---
class TestNimSettingsValidBounds:
    """Test that valid values within bounds are accepted."""

    @pytest.mark.parametrize("top_k", [-1, 0, 1, 100])
    def test_top_k_valid(self, top_k):
        """top_k >= -1 should be accepted."""
        s = NimSettings(top_k=top_k)
        assert s.top_k == top_k

    @pytest.mark.parametrize("temp", [0.0, 0.5, 1.0, 2.0])
    def test_temperature_valid(self, temp):
        s = NimSettings(temperature=temp)
        assert s.temperature == temp

    @pytest.mark.parametrize("top_p", [0.0, 0.5, 1.0])
    def test_top_p_valid(self, top_p):
        s = NimSettings(top_p=top_p)
        assert s.top_p == top_p

    def test_max_tokens_valid(self):
        s = NimSettings(max_tokens=1)
        assert s.max_tokens == 1

    def test_min_tokens_valid(self):
        s = NimSettings(min_tokens=0)
        assert s.min_tokens == 0

    @pytest.mark.parametrize("penalty", [-2.0, 0.0, 2.0])
    def test_presence_penalty_valid(self, penalty):
        s = NimSettings(presence_penalty=penalty)
        assert s.presence_penalty == penalty

    @pytest.mark.parametrize("penalty", [-2.0, 0.0, 2.0])
    def test_frequency_penalty_valid(self, penalty):
        s = NimSettings(frequency_penalty=penalty)
        assert s.frequency_penalty == penalty

    @pytest.mark.parametrize("min_p", [0.0, 0.5, 1.0])
    def test_min_p_valid(self, min_p):
        s = NimSettings(min_p=min_p)
        assert s.min_p == min_p


class TestNimSettingsInvalidBounds:
    """Test that out-of-range values raise ValidationError."""

    @pytest.mark.parametrize("top_k", [-2, -100])
    def test_top_k_below_lower_bound(self, top_k):
        with pytest.raises((ValidationError, ValueError)):
            NimSettings(top_k=top_k)

    def test_temperature_negative(self):
        with pytest.raises(ValidationError):
            NimSettings(temperature=-0.1)

    @pytest.mark.parametrize("top_p", [-0.1, 1.1])
    def test_top_p_out_of_range(self, top_p):
        with pytest.raises(ValidationError):
            NimSettings(top_p=top_p)

    @pytest.mark.parametrize("penalty", [-2.1, 2.1])
    def test_presence_penalty_out_of_range(self, penalty):
        with pytest.raises(ValidationError):
            NimSettings(presence_penalty=penalty)

    @pytest.mark.parametrize("penalty", [-2.1, 2.1])
    def test_frequency_penalty_out_of_range(self, penalty):
        with pytest.raises(ValidationError):
            NimSettings(frequency_penalty=penalty)

    @pytest.mark.parametrize("min_p", [-0.1, 1.1])
    def test_min_p_out_of_range(self, min_p):
        with pytest.raises(ValidationError):
            NimSettings(min_p=min_p)

    @pytest.mark.parametrize("max_tokens", [0, -1])
    def test_max_tokens_too_low(self, max_tokens):
        with pytest.raises(ValidationError):
            NimSettings(max_tokens=max_tokens)

    def test_min_tokens_negative(self):
        with pytest.raises(ValidationError):
            NimSettings(min_tokens=-1)


class TestNimSettingsValidators:
    """Test custom field validators in NimSettings."""

    def test_default_max_tokens_matches_shared_constant(self):
        assert NimSettings().max_tokens == ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS

    @pytest.mark.parametrize(
        "seed_val,expected",
        [("", None), (None, None), ("42", 42), (42, 42)],
        ids=["empty_str", "none", "str_42", "int_42"],
    )
    def test_parse_optional_int(self, seed_val, expected):
        s = NimSettings(seed=seed_val)
        assert s.seed == expected

    @pytest.mark.parametrize(
        "stop_val,expected",
        [("", None), ("STOP", "STOP"), (None, None)],
        ids=["empty_str", "valid", "none"],
    )
    def test_parse_optional_str_stop(self, stop_val, expected):
        s = NimSettings(stop=stop_val)
        assert s.stop == expected

    @pytest.mark.parametrize(
        "chat_template_val,expected",
        [("", None), ("template", "template")],
        ids=["empty_str", "valid"],
    )
    def test_parse_optional_str_chat_template(self, chat_template_val, expected):
        s = NimSettings(chat_template=chat_template_val)
        assert s.chat_template == expected

    def test_extra_forbid_rejects_unknown_field(self):
        """NimSettings with extra='forbid' rejects unknown fields."""
        from typing import Any, cast

        with pytest.raises(ValidationError):
            NimSettings(**cast(Any, {"unknown_field": "value"}))

    def test_enable_thinking_field_removed(self):
        """NimSettings no longer accepts the removed thinking toggle."""
        from typing import Any, cast

        with pytest.raises(ValidationError):
            NimSettings(**cast(Any, {"enable_thinking": True}))


class TestSettingsOptionalStr:
    """Test Settings parse_optional_str validator."""

    def test_empty_telegram_token_to_none(self, monkeypatch):

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        s = Settings()
        assert s.telegram_bot_token is None

    def test_valid_telegram_token_preserved(self, monkeypatch):

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
        s = Settings()
        assert s.telegram_bot_token == "abc123"

    def test_empty_allowed_user_id_to_none(self, monkeypatch):

        monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", "")
        s = Settings()
        assert s.allowed_telegram_user_id is None

    def test_discord_bot_token_from_env(self, monkeypatch):

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord_token_123")
        s = Settings()
        assert s.discord_bot_token == "discord_token_123"

    def test_empty_discord_bot_token_to_none(self, monkeypatch):

        monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
        s = Settings()
        assert s.discord_bot_token is None

    def test_allowed_discord_channels_from_env(self, monkeypatch):

        monkeypatch.setenv("ALLOWED_DISCORD_CHANNELS", "111,222,333")
        s = Settings()
        assert s.allowed_discord_channels == "111,222,333"

    def test_messaging_platform_from_env(self, monkeypatch):

        monkeypatch.setenv("MESSAGING_PLATFORM", "discord")
        s = Settings()
        assert s.messaging_platform == "discord"

    def test_whisper_device_auto_rejected(self, monkeypatch):
        """WHISPER_DEVICE=auto raises ValidationError (auto removed)."""

        monkeypatch.setenv("WHISPER_DEVICE", "auto")
        with pytest.raises(ValidationError, match="whisper_device"):
            Settings()

    @pytest.mark.parametrize("device", ["cpu", "cuda"])
    def test_whisper_device_valid(self, monkeypatch, device):
        """Valid whisper_device values are accepted."""

        monkeypatch.setenv("WHISPER_DEVICE", device)
        s = Settings()
        assert s.whisper_device == device


class TestPerModelMapping:
    """Test resolve_model and resolve_thinking with custom models."""

    def test_model_fields_default_empty(self, monkeypatch):
        """custom_models defaults to empty dict."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        s = Settings()
        assert s.custom_models == {}

    def test_resolve_model_fallback_when_no_custom(self, monkeypatch):
        """resolve_model falls back to self.model when no custom models."""

        monkeypatch.setitem(Settings.model_config, "env_file", ())
        s = Settings()
        s.model = "nvidia_nim/fallback-model"
        assert s.resolve_model("unknown-model") == "nvidia_nim/fallback-model"

    def test_resolve_model_custom_exact_match(self, monkeypatch):
        """resolve_model returns exact match for custom models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        s = Settings()
        assert s.resolve_model("ollama/glm-5.1:cloud") == "ollama/glm-5.1:cloud"

    def test_resolve_thinking_custom(self, monkeypatch):
        """resolve_thinking returns per-model thinking for custom models."""

        monkeypatch.setenv("MODEL_1", "ollama/glm-5.1:cloud")
        monkeypatch.setenv("ENABLE_MODEL_1_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        s = Settings()
        assert s.resolve_thinking("ollama/glm-5.1:cloud") is False

    def test_resolve_thinking_inherits_default(self, monkeypatch):
        """resolve_thinking inherits enable_model_thinking for unknown models."""

        monkeypatch.setenv("ENABLE_MODEL_THINKING", "false")
        monkeypatch.setitem(Settings.model_config, "env_file", ())
        s = Settings()
        assert s.resolve_thinking("unknown-model") is False

    def test_parse_provider_type(self):
        """parse_provider_type extracts provider from model string."""

        assert Settings.parse_provider_type("nvidia_nim/meta/llama") == "nvidia_nim"
        assert Settings.parse_provider_type("open_router/deepseek/r1") == "open_router"
        assert Settings.parse_provider_type("deepseek/deepseek-chat") == "deepseek"
        assert Settings.parse_provider_type("lmstudio/qwen") == "lmstudio"
        assert Settings.parse_provider_type("llamacpp/model") == "llamacpp"
        assert Settings.parse_provider_type("ollama/llama3.1") == "ollama"

    def test_parse_model_name(self):
        """parse_model_name extracts model name from model string."""

        assert Settings.parse_model_name("nvidia_nim/meta/llama") == "meta/llama"
        assert Settings.parse_model_name("deepseek/deepseek-chat") == "deepseek-chat"
        assert Settings.parse_model_name("lmstudio/qwen") == "qwen"
        assert Settings.parse_model_name("llamacpp/model") == "model"
        assert Settings.parse_model_name("ollama/llama3.1") == "llama3.1"

    def test_provider_display(self):
        """provider_display converts model refs to human-readable labels."""
        assert provider_display("ollama/glm-5.1:cloud") == "Ollama › glm-5.1:cloud"  # noqa: RUF001
        assert provider_display("nvidia_nim/z-ai/glm4.7") == "Nvidia Nim › z-ai/glm4.7"  # noqa: RUF001
        assert (
            provider_display("open_router/deepseek/r1") == "Open Router › deepseek/r1"  # noqa: RUF001
        )
        assert provider_display("") == ""
