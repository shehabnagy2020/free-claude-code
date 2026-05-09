"""Centralized configuration using Pydantic Settings."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import HTTP_CONNECT_TIMEOUT_DEFAULT
from .nim import NimSettings
from .provider_ids import SUPPORTED_PROVIDER_IDS


@dataclass(frozen=True, slots=True)
class CustomModelEntry:
    """A user-defined model entry discovered from MODEL_N environment variables."""

    model_ref: str
    thinking_enabled: bool


@dataclass(frozen=True, slots=True)
class ConfiguredChatModelRef:
    """A provider/model ref with its source env key."""

    model_ref: str
    provider_id: str
    model_id: str
    sources: tuple[str, ...]


def _env_files() -> tuple[Path, ...]:
    """Return env file paths in priority order (later overrides earlier)."""
    files: list[Path] = [
        Path.home() / ".config" / "free-claude-code" / ".env",
        Path(".env"),
    ]
    if explicit := os.environ.get("FCC_ENV_FILE"):
        files.append(Path(explicit))
    return tuple(files)


def _configured_env_files(model_config: Mapping[str, Any]) -> tuple[Path, ...]:
    """Return the currently configured env files for Settings."""
    configured = model_config.get("env_file")
    if configured is None:
        return ()
    if isinstance(configured, (str, Path)):
        return (Path(configured),)
    return tuple(Path(item) for item in configured)


def _env_file_contains_key(path: Path, key: str) -> bool:
    """Check whether a dotenv-style file defines the given key."""
    return _env_file_value(path, key) is not None


def _env_file_value(path: Path, key: str) -> str | None:
    """Return a dotenv value when the file explicitly defines the key."""
    if not path.is_file():
        return None

    try:
        values = dotenv_values(path)
    except OSError:
        return None

    if key not in values:
        return None
    value = values[key]
    return "" if value is None else value


def _env_file_override(model_config: Mapping[str, Any], key: str) -> str | None:
    """Return the last configured dotenv value that explicitly defines a key."""
    configured_value: str | None = None
    for env_file in _configured_env_files(model_config):
        value = _env_file_value(env_file, key)
        if value is not None:
            configured_value = value
    return configured_value


_CUSTOM_MODEL_PATTERN = re.compile(r"^MODEL_(\d+)$")


def _discover_custom_models(
    env_sources: Mapping[str, str],
    enable_model_thinking: bool,
) -> dict[str, CustomModelEntry]:
    """Scan env sources for MODEL_N keys and build ordered custom models dict.

    Args:
        env_sources: Merged env key-value pairs (dotenv then process env).
        enable_model_thinking: Global default for thinking.

    Returns:
        Ordered dict keyed by model ref (e.g. "ollama/glm-5.1:cloud").
    """
    indexed: list[tuple[int, str]] = []
    for key, value in env_sources.items():
        m = _CUSTOM_MODEL_PATTERN.match(key)
        if m and value.strip():
            idx = int(m.group(1))
            model_ref = value.strip()
            if "/" not in model_ref:
                raise ValueError(
                    f"MODEL_{idx} must be prefixed with provider type. "
                    f"Valid providers: {', '.join(SUPPORTED_PROVIDER_IDS)}. "
                    f"Format: provider_type/model/name"
                )
            provider = model_ref.split("/", 1)[0]
            if provider not in SUPPORTED_PROVIDER_IDS:
                supported = ", ".join(f"'{p}'" for p in SUPPORTED_PROVIDER_IDS)
                raise ValueError(
                    f"MODEL_{idx}: Invalid provider '{provider}'. Supported: {supported}"
                )
            indexed.append((idx, model_ref))

    indexed.sort(key=lambda t: t[0])

    custom: dict[str, CustomModelEntry] = {}
    for idx, model_ref in indexed:
        thinking_key = f"ENABLE_MODEL_{idx}_THINKING"
        thinking_val = env_sources.get(thinking_key, "").strip().lower()
        if thinking_val in ("true", "1", "yes"):
            thinking = True
        elif thinking_val in ("false", "0", "no"):
            thinking = False
        else:
            thinking = enable_model_thinking
        custom[model_ref] = CustomModelEntry(
            model_ref=model_ref,
            thinking_enabled=thinking,
        )

    return custom


def _merge_env_for_custom_models(model_config: Mapping[str, Any]) -> dict[str, str]:
    """Merge dotenv file values with process env, process env takes precedence."""
    merged: dict[str, str] = {}
    for env_file in _configured_env_files(model_config):
        try:
            values = dotenv_values(env_file)
        except OSError:
            continue
        merged.update({k: v for k, v in values.items() if v is not None})
    merged.update({k: v for k, v in os.environ.items() if v is not None})
    return merged


def provider_display(model_str: str) -> str:
    """Convert 'provider_type/model/name' to human-readable provider label."""
    if not model_str:
        return ""
    parts = model_str.split("/", 1)
    provider_id = parts[0]
    model_name = parts[1] if len(parts) > 1 else ""
    provider_label = provider_id.replace("_", " ").title()
    return f"{provider_label} › {model_name}" if model_name else provider_label  # noqa: RUF001


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ==================== OpenRouter Config ====================
    open_router_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")

    # ==================== DeepSeek Config ====================
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")

    # ==================== Google Gemini Config ====================
    google_gemini_api_key: str = Field(
        default="", validation_alias="GOOGLE_GEMINI_API_KEY"
    )

    # ==================== Messaging Platform Selection ====================
    # Valid: "telegram" | "discord" | "none"
    messaging_platform: str = Field(
        default="discord", validation_alias="MESSAGING_PLATFORM"
    )
    messaging_rate_limit: int = Field(
        default=1, validation_alias="MESSAGING_RATE_LIMIT"
    )
    messaging_rate_window: float = Field(
        default=1.0, validation_alias="MESSAGING_RATE_WINDOW"
    )

    # ==================== NVIDIA NIM Config ====================
    nvidia_nim_api_key: str = ""

    # ==================== LM Studio Config ====================
    lm_studio_base_url: str = Field(
        default="http://localhost:1234/v1",
        validation_alias="LM_STUDIO_BASE_URL",
    )

    # ==================== Llama.cpp Config ====================
    llamacpp_base_url: str = Field(
        default="http://localhost:8080/v1",
        validation_alias="LLAMACPP_BASE_URL",
    )

    # ==================== Ollama Config ====================
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )

    # ==================== Model ====================
    # Default model: used when no MODEL_N custom models match.
    # Format: provider_type/model/name
    model: str = "nvidia_nim/z-ai/glm4.7"

    # Dynamic custom models discovered from MODEL_N env vars.
    # Populated by discover_custom_models validator.
    custom_models: dict[str, CustomModelEntry] = Field(default_factory=dict)

    # ==================== Per-Provider Proxy ====================
    nvidia_nim_proxy: str = Field(default="", validation_alias="NVIDIA_NIM_PROXY")
    google_gemini_proxy: str = Field(default="", validation_alias="GOOGLE_GEMINI_PROXY")
    open_router_proxy: str = Field(default="", validation_alias="OPENROUTER_PROXY")
    lmstudio_proxy: str = Field(default="", validation_alias="LMSTUDIO_PROXY")
    llamacpp_proxy: str = Field(default="", validation_alias="LLAMACPP_PROXY")

    # ==================== Provider Rate Limiting ====================
    provider_rate_limit: int = Field(default=20, validation_alias="PROVIDER_RATE_LIMIT")
    provider_rate_window: int = Field(
        default=60, validation_alias="PROVIDER_RATE_WINDOW"
    )
    provider_max_concurrency: int = Field(
        default=2, validation_alias="PROVIDER_MAX_CONCURRENCY"
    )
    enable_model_thinking: bool = Field(
        default=True, validation_alias="ENABLE_MODEL_THINKING"
    )

    # ==================== HTTP Client Timeouts ====================
    http_read_timeout: float = Field(
        default=300.0, validation_alias="HTTP_READ_TIMEOUT"
    )
    http_write_timeout: float = Field(
        default=60.0, validation_alias="HTTP_WRITE_TIMEOUT"
    )
    http_connect_timeout: float = Field(
        default=HTTP_CONNECT_TIMEOUT_DEFAULT,
        validation_alias="HTTP_CONNECT_TIMEOUT",
    )

    # ==================== Fast Prefix Detection ====================
    fast_prefix_detection: bool = True

    # ==================== Optimizations ====================
    enable_network_probe_mock: bool = True
    enable_title_generation_skip: bool = True
    enable_suggestion_mode_skip: bool = True
    enable_filepath_extraction_mock: bool = True

    # ==================== Local web server tools (web_search / web_fetch) ====================
    # Off by default: these tools perform outbound HTTP from the proxy (SSRF risk).
    enable_web_server_tools: bool = Field(
        default=False, validation_alias="ENABLE_WEB_SERVER_TOOLS"
    )
    # Optional Tavily API key (tvly-...). Get yours at https://tavily.com.
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")

    # When set, web_search and web_fetch use the Tavily REST API.
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")
    # Comma-separated URL schemes allowed for web_fetch (default: http,https).
    web_fetch_allowed_schemes: str = Field(
        default="http,https", validation_alias="WEB_FETCH_ALLOWED_SCHEMES"
    )
    # When true, skip private/loopback/link-local IP blocking for web_fetch (lab only).
    web_fetch_allow_private_networks: bool = Field(
        default=False, validation_alias="WEB_FETCH_ALLOW_PRIVATE_NETWORKS"
    )

    # ==================== Debug / diagnostic logging (avoid sensitive content) ====================
    # When false (default), API and SSE helpers log only metadata (counts, lengths, ids).
    log_raw_api_payloads: bool = Field(
        default=False, validation_alias="LOG_RAW_API_PAYLOADS"
    )
    log_raw_sse_events: bool = Field(
        default=False, validation_alias="LOG_RAW_SSE_EVENTS"
    )
    # When false (default), unhandled exceptions log only type + route metadata (no message/traceback).
    log_api_error_tracebacks: bool = Field(
        default=False, validation_alias="LOG_API_ERROR_TRACEBACKS"
    )
    # When false (default), messaging logs omit text/transcription previews (metadata only).
    log_raw_messaging_content: bool = Field(
        default=False, validation_alias="LOG_RAW_MESSAGING_CONTENT"
    )
    # When true, log full Claude CLI stderr, non-JSON lines, and parser error text.
    log_raw_cli_diagnostics: bool = Field(
        default=False, validation_alias="LOG_RAW_CLI_DIAGNOSTICS"
    )
    # When true, log exception text / CLI error strings in messaging (may leak user content).
    log_messaging_error_details: bool = Field(
        default=False, validation_alias="LOG_MESSAGING_ERROR_DETAILS"
    )
    debug_platform_edits: bool = Field(
        default=False, validation_alias="DEBUG_PLATFORM_EDITS"
    )
    debug_subagent_stack: bool = Field(
        default=False, validation_alias="DEBUG_SUBAGENT_STACK"
    )

    # ==================== NIM Settings ====================
    nim: NimSettings = Field(default_factory=NimSettings)

    # ==================== Voice Note Transcription ====================
    voice_note_enabled: bool = Field(
        default=True, validation_alias="VOICE_NOTE_ENABLED"
    )
    # Device: "cpu" | "cuda" | "nvidia_nim"
    # - "cpu"/"cuda": local Whisper (requires voice_local extra: uv sync --extra voice_local)
    # - "nvidia_nim": NVIDIA NIM Whisper API (requires voice extra: uv sync --extra voice)
    whisper_device: str = Field(default="cpu", validation_alias="WHISPER_DEVICE")
    # Whisper model ID or short name (for local Whisper) or NVIDIA NIM model (for nvidia_nim)
    # Local Whisper: "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"
    # NVIDIA NIM: "nvidia/parakeet-ctc-1.1b-asr", "openai/whisper-large-v3", etc.
    whisper_model: str = Field(default="base", validation_alias="WHISPER_MODEL")
    # Hugging Face token for faster model downloads (optional, for local Whisper)
    hf_token: str = Field(default="", validation_alias="HF_TOKEN")

    # ==================== Bot Wrapper Config ====================
    telegram_bot_token: str | None = None
    allowed_telegram_user_id: str | None = None
    discord_bot_token: str | None = Field(
        default=None, validation_alias="DISCORD_BOT_TOKEN"
    )
    allowed_discord_channels: str | None = Field(
        default=None, validation_alias="ALLOWED_DISCORD_CHANNELS"
    )
    claude_workspace: str = "./agent_workspace"
    allowed_dir: str = ""
    claude_cli_bin: str = Field(default="claude", validation_alias="CLAUDE_CLI_BIN")
    max_message_log_entries_per_chat: int | None = Field(
        default=None, validation_alias="MAX_MESSAGE_LOG_ENTRIES_PER_CHAT"
    )

    # ==================== Web Chat UI ====================
    # Password for the built-in web chat UI. Change via UI_PASSWORD in .env.
    ui_password: str = Field(default="Shehab", validation_alias="UI_PASSWORD")

    # ==================== Server ====================
    host: str = "0.0.0.0"
    port: int = 8082
    log_file: str = "server.log"
    # Optional server API key to protect endpoints (Anthropic-style)
    # Set via env `ANTHROPIC_AUTH_TOKEN`. When empty, no auth is required.
    anthropic_auth_token: str = Field(
        default="", validation_alias="ANTHROPIC_AUTH_TOKEN"
    )

    @model_validator(mode="before")
    @classmethod
    def reject_removed_env_vars(cls, data: Any) -> Any:
        """Fail fast when removed environment variables are still configured."""
        removed_keys = (
            "NIM_ENABLE_THINKING",
            "ENABLE_THINKING",
            "MODEL_OPUS",
            "MODEL_SONNET",
            "MODEL_HAIKU",
            "ENABLE_OPUS_THINKING",
            "ENABLE_SONNET_THINKING",
            "ENABLE_HAIKU_THINKING",
        )
        replacement = "MODEL_N (e.g. MODEL_1) and ENABLE_MODEL_N_THINKING (e.g. ENABLE_MODEL_1_THINKING)"

        for removed_key in removed_keys:
            if removed_key in os.environ:
                raise ValueError(
                    f"{removed_key} has been removed in this release. "
                    f"Use {replacement} instead."
                )

            for env_file in _configured_env_files(
                data if isinstance(data, dict) else {}
            ):
                if _env_file_contains_key(env_file, removed_key):
                    raise ValueError(
                        f"{removed_key} has been removed in this release. "
                        f"Use {replacement} instead. Found in {env_file}."
                    )

        return data

    @field_validator(
        "telegram_bot_token",
        "allowed_telegram_user_id",
        "discord_bot_token",
        "allowed_discord_channels",
        mode="before",
    )
    @classmethod
    def parse_optional_str(cls, v: Any) -> Any:
        if v == "":
            return None
        return v

    @field_validator("max_message_log_entries_per_chat", mode="before")
    @classmethod
    def parse_optional_log_cap(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v

    @field_validator("whisper_device")
    @classmethod
    def validate_whisper_device(cls, v: str) -> str:
        if v not in ("cpu", "cuda", "nvidia_nim"):
            raise ValueError(
                f"whisper_device must be 'cpu', 'cuda', or 'nvidia_nim', got {v!r}"
            )
        return v

    @field_validator("messaging_platform")
    @classmethod
    def validate_messaging_platform(cls, v: str) -> str:
        if v not in ("telegram", "discord", "none"):
            raise ValueError(
                f"messaging_platform must be 'telegram', 'discord', or 'none', got {v!r}"
            )
        return v

    @field_validator("messaging_rate_limit")
    @classmethod
    def validate_messaging_rate_limit(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("messaging_rate_limit must be > 0")
        return v

    @field_validator("messaging_rate_window")
    @classmethod
    def validate_messaging_rate_window(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("messaging_rate_window must be > 0")
        return float(v)

    @field_validator("web_fetch_allowed_schemes")
    @classmethod
    def validate_web_fetch_allowed_schemes(cls, v: str) -> str:
        schemes = [part.strip().lower() for part in v.split(",") if part.strip()]
        if not schemes:
            raise ValueError("web_fetch_allowed_schemes must list at least one scheme")
        for scheme in schemes:
            if not scheme.isascii() or not scheme.isalpha():
                raise ValueError(
                    f"Invalid URL scheme in web_fetch_allowed_schemes: {scheme!r}"
                )
        return ",".join(schemes)

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, v: str) -> str:
        if v.rstrip("/").endswith("/v1"):
            raise ValueError(
                "OLLAMA_BASE_URL must be the Ollama root URL for native Anthropic "
                "messages, e.g. http://localhost:11434 (without /v1)."
            )
        return v

    @field_validator("model")
    @classmethod
    def validate_model_format(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError(
                f"Model must be prefixed with provider type. "
                f"Valid providers: {', '.join(SUPPORTED_PROVIDER_IDS)}. "
                f"Format: provider_type/model/name"
            )
        provider = v.split("/", 1)[0]
        if provider not in SUPPORTED_PROVIDER_IDS:
            supported = ", ".join(f"'{p}'" for p in SUPPORTED_PROVIDER_IDS)
            raise ValueError(f"Invalid provider: '{provider}'. Supported: {supported}")
        return v

    @model_validator(mode="after")
    def discover_custom_models(self) -> Settings:
        """Scan env vars and dotenv files for MODEL_N entries."""
        merged = _merge_env_for_custom_models(self.model_config)
        self.custom_models = _discover_custom_models(merged, self.enable_model_thinking)
        return self

    @model_validator(mode="after")
    def auto_enable_web_tools_for_tavily(self) -> Settings:
        """Auto-enable web server tools when a Tavily API key is configured."""
        if self.tavily_api_key and not self.enable_web_server_tools:
            self.enable_web_server_tools = True
        return self

    @model_validator(mode="after")
    def check_nvidia_nim_api_key(self) -> Settings:
        if (
            self.voice_note_enabled
            and self.whisper_device == "nvidia_nim"
            and not self.nvidia_nim_api_key.strip()
        ):
            raise ValueError(
                "NVIDIA_NIM_API_KEY is required when WHISPER_DEVICE is 'nvidia_nim'. "
                "Set it in your .env file."
            )
        return self

    @model_validator(mode="after")
    def prefer_dotenv_anthropic_auth_token(self) -> Settings:
        """Let explicit .env auth config override stale shell/client tokens."""
        dotenv_value = _env_file_override(self.model_config, "ANTHROPIC_AUTH_TOKEN")
        if dotenv_value is not None:
            self.anthropic_auth_token = dotenv_value
        return self

    def uses_process_anthropic_auth_token(self) -> bool:
        """Return whether proxy auth came from process env, not dotenv config."""
        if _env_file_override(self.model_config, "ANTHROPIC_AUTH_TOKEN") is not None:
            return False
        return bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    @property
    def provider_type(self) -> str:
        """Extract provider type from the default model string."""
        return Settings.parse_provider_type(self.model)

    @property
    def model_name(self) -> str:
        """Extract the actual model name from the default model string."""
        return Settings.parse_model_name(self.model)

    def configured_chat_model_refs(self) -> tuple[ConfiguredChatModelRef, ...]:
        """Return unique configured chat provider/model refs with source env keys."""
        sources_by_ref: dict[str, list[str]] = {}
        sources_by_ref.setdefault(self.model, []).append("MODEL")
        for entry in self.custom_models.values():
            sources_by_ref.setdefault(entry.model_ref, []).append("MODEL_N")

        return tuple(
            ConfiguredChatModelRef(
                model_ref=model_ref,
                provider_id=Settings.parse_provider_type(model_ref),
                model_id=Settings.parse_model_name(model_ref),
                sources=tuple(sources),
            )
            for model_ref, sources in sources_by_ref.items()
        )

    def resolve_model(self, model_name: str) -> str:
        """Resolve a model name to the configured provider/model string.

        Handles gateway-prefixed IDs (e.g. "anthropic/nvidia_nim/z-ai/glm4.7")
        by stripping the prefix. Falls back to default MODEL for unknown names.
        """
        # Gateway-prefixed model IDs
        if model_name.startswith("anthropic/") or model_name.startswith(
            "claude-3-freecc-no-thinking/"
        ):
            _, _, remainder = model_name.partition("/")
            # remainder is like "nvidia_nim/z-ai/glm4.7"
            if remainder in self.custom_models:
                return remainder
            # Only accept remainder if it has a known provider prefix
            provider = remainder.split("/", 1)[0] if "/" in remainder else ""
            if provider in SUPPORTED_PROVIDER_IDS:
                return remainder
            return self.model

        # Direct provider-prefixed model IDs
        if model_name in self.custom_models:
            return self.custom_models[model_name].model_ref
        return self.model

    def resolve_thinking(self, model_name: str) -> bool:
        """Resolve whether thinking is enabled for a model name."""
        # No-thinking gateway prefix explicitly disables thinking
        if model_name.startswith("claude-3-freecc-no-thinking/"):
            return False
        # Anthropic gateway prefix inherits per-model thinking setting
        if model_name.startswith("anthropic/"):
            _, _, remainder = model_name.partition("/")
            if remainder in self.custom_models:
                return self.custom_models[remainder].thinking_enabled
            return self.enable_model_thinking

        if model_name in self.custom_models:
            return self.custom_models[model_name].thinking_enabled
        return self.enable_model_thinking

    def get_models_list(self) -> list[dict[str, str]]:
        """Return list of model dicts for /v1/models and UI config endpoints.

        Each dict has keys: id, display_name, created_at.
        When custom models are defined, uses them directly.
        Otherwise falls back to the default model only.
        """
        if self.custom_models:
            return [
                {
                    "id": model_ref,
                    "display_name": provider_display(model_ref),
                    "created_at": "2025-01-01T00:00:00Z",
                }
                for model_ref in self.custom_models
            ]
        return [
            {
                "id": self.model,
                "display_name": provider_display(self.model),
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]

    def web_fetch_allowed_scheme_set(self) -> frozenset[str]:
        """Return normalized schemes allowed for web_fetch."""
        return frozenset(
            part.strip().lower()
            for part in self.web_fetch_allowed_schemes.split(",")
            if part.strip()
        )

    @staticmethod
    def parse_provider_type(model_string: str) -> str:
        """Extract provider type from any 'provider/model' string."""
        return model_string.split("/", 1)[0]

    @staticmethod
    def parse_model_name(model_string: str) -> str:
        """Extract model name from any 'provider/model' string."""
        return model_string.split("/", 1)[1]

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
