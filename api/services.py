"""Application services for the Claude-compatible API."""

from __future__ import annotations

import traceback
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from config.settings import Settings
from core.anthropic import get_token_count, get_user_facing_error_message
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from providers.base import BaseProvider
from providers.exceptions import InvalidRequestError, ProviderError

from config.provider_catalog import PROVIDER_CATALOG

from .model_router import ModelRouter
from .models.anthropic import MessagesRequest, TokenCountRequest
from .models.responses import TokenCountResponse
from .optimization_handlers import try_optimizations
from .web_tools.egress import WebFetchEgressPolicy
from .web_tools.request import (
    has_listed_anthropic_server_tools,
    inject_web_search_system_prompt,
    is_web_server_tool_request,
    openai_chat_upstream_server_tool_error,
    strip_server_tools,
)
from .web_tools.streaming import stream_web_server_tool_response

TokenCounter = Callable[[list[Any], str | list[Any] | None, list[Any] | None], int]

ProviderGetter = Callable[[str], BaseProvider]

# Providers that use ``/chat/completions`` + Anthropic-to-OpenAI conversion (not native Messages).
# Derived from the catalog so new openai_chat-transport providers auto-qualify.
_OPENAI_CHAT_UPSTREAM_IDS = frozenset(
    pid for pid, d in PROVIDER_CATALOG.items() if d.transport_type == "openai_chat"
)


def anthropic_sse_streaming_response(
    body: AsyncIterator[str],
) -> StreamingResponse:
    """Return a :class:`StreamingResponse` for Anthropic-style SSE streams."""
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )


def _http_status_for_unexpected_service_exception(_exc: BaseException) -> int:
    """HTTP status for uncaught non-provider failures (stable client contract)."""
    return 500


def _log_unexpected_service_exception(
    settings: Settings,
    exc: BaseException,
    *,
    context: str,
    request_id: str | None = None,
) -> None:
    """Log service-layer failures without echoing exception text unless opted in."""
    if settings.log_api_error_tracebacks:
        if request_id is not None:
            logger.error("{} request_id={}: {}", context, request_id, exc)
        else:
            logger.error("{}: {}", context, exc)
        logger.error(traceback.format_exc())
        return
    if request_id is not None:
        logger.error(
            "{} request_id={} exc_type={}",
            context,
            request_id,
            type(exc).__name__,
        )
    else:
        logger.error("{} exc_type={}", context, type(exc).__name__)


def _require_non_empty_messages(messages: list[Any]) -> None:
    if not messages:
        raise InvalidRequestError("messages cannot be empty")


class ClaudeProxyService:
    """Coordinate request optimization, model routing, token count, and providers."""

    def __init__(
        self,
        settings: Settings,
        provider_getter: ProviderGetter,
        model_router: ModelRouter | None = None,
        token_counter: TokenCounter = get_token_count,
    ):
        self._settings = settings
        self._provider_getter = provider_getter
        self._model_router = model_router or ModelRouter(settings)
        self._token_counter = token_counter

    def create_message(self, request_data: MessagesRequest) -> object:
        """Create a message response or streaming response."""
        try:
            _require_non_empty_messages(request_data.messages)

            logger.info(
                "[1/6] REQUEST received: model={} messages={} tools={} tool_choice={}",
                request_data.model,
                len(request_data.messages),
                [t.name for t in (request_data.tools or [])],
                request_data.tool_choice,
            )
            if request_data.tools:
                for t in request_data.tools:
                    if t.name in ("web_search", "web_fetch") or (t.type and ("web_search" in t.type or "web_fetch" in t.type)):
                        logger.info("  -> server tool detected: name={!r} type={!r}", t.name, t.type)

            routed = self._model_router.resolve_messages_request(request_data)
            logger.info(
                "[2/6] ROUTED: original={} provider={} provider_model={} thinking={}",
                routed.resolved.original_model,
                routed.resolved.provider_id,
                routed.resolved.provider_model,
                routed.resolved.thinking_enabled,
            )

            if routed.resolved.provider_id in _OPENAI_CHAT_UPSTREAM_IDS:
                tool_err = openai_chat_upstream_server_tool_error(
                    routed.request,
                    web_tools_enabled=self._settings.enable_web_server_tools,
                )
                if tool_err is not None:
                    raise InvalidRequestError(tool_err)

            # ----- Web server tool handling (web_search / web_fetch) -----
            web_tools_listed = has_listed_anthropic_server_tools(routed.request)
            logger.info(
                "[3/6] WEB_TOOLS: listed={} enabled={} is_forced={}",
                web_tools_listed,
                self._settings.enable_web_server_tools,
                is_web_server_tool_request(routed.request),
            )

            if web_tools_listed and self._settings.enable_web_server_tools:
                if is_web_server_tool_request(routed.request):
                    # Forced tool_choice: proxy handles the entire turn via Tavily.
                    input_tokens = self._token_counter(
                        routed.request.messages,
                        routed.request.system,
                        routed.request.tools,
                    )
                    logger.info(
                        "[4/6] TAVILY forced web tool: tool={} key_set={} input_tokens={}",
                        routed.request.tool_choice,
                        bool(self._settings.tavily_api_key),
                        input_tokens,
                    )
                    egress = WebFetchEgressPolicy(
                        allow_private_network_targets=self._settings.web_fetch_allow_private_networks,
                        allowed_schemes=self._settings.web_fetch_allowed_scheme_set(),
                    )
                    return anthropic_sse_streaming_response(
                        stream_web_server_tool_response(
                            routed.request,
                            input_tokens=input_tokens,
                            web_fetch_egress=egress,
                            verbose_client_errors=self._settings.log_api_error_tracebacks,
                            tavily_api_key=self._settings.tavily_api_key,
                        ),
                    )
                # Auto tool_choice with server tools listed: fall through to
                # normal provider routing. strip_server_tools() will remove the
                # server tool definitions below. The CLI will issue a separate
                # forced tool_choice request when it decides to search.
                logger.info("[4/6] WEB_TOOLS listed but not forced — injecting system prompt and routing to provider")

            optimized = try_optimizations(routed.request, self._settings)
            if optimized is not None:
                logger.info("[4/6] OPTIMIZATION matched, returning fast-path response")
                return optimized
            logger.info("[4/6] No optimization matched, routing to provider")

            # Strip Anthropic server tool definitions (web_search / web_fetch) before
            # forwarding — providers never handle these; the proxy does.
            forward_request = strip_server_tools(routed.request)

            # When web tools were listed, inject a system prompt instruction so the
            # model calls web_search instead of answering from training data.
            if web_tools_listed and self._settings.enable_web_server_tools:
                forward_request = inject_web_search_system_prompt(forward_request)
                logger.info("[5b] Injected web_search system prompt instruction")
            stripped_tools = [t.name for t in (forward_request.tools or [])]
            logger.info(
                "[5/6] FORWARD: provider={} model={} messages={} tools={}",
                routed.resolved.provider_id,
                forward_request.model,
                len(forward_request.messages),
                stripped_tools,
            )

            provider = self._provider_getter(routed.resolved.provider_id)
            provider.preflight_stream(
                forward_request,
                thinking_enabled=routed.resolved.thinking_enabled,
            )

            request_id = f"req_{uuid.uuid4().hex[:12]}"
            logger.info(
                "[6/6] STREAMING request_id={} model={} messages={}",
                request_id,
                forward_request.model,
                len(forward_request.messages),
            )
            if self._settings.log_raw_api_payloads:
                logger.debug(
                    "FULL_PAYLOAD [{}]: {}", request_id, forward_request.model_dump()
                )

            input_tokens = self._token_counter(
                forward_request.messages, forward_request.system, forward_request.tools
            )
            return anthropic_sse_streaming_response(
                provider.stream_response(
                    forward_request,
                    input_tokens=input_tokens,
                    request_id=request_id,
                    thinking_enabled=routed.resolved.thinking_enabled,
                ),
            )

        except ProviderError:
            raise
        except Exception as e:
            _log_unexpected_service_exception(
                self._settings, e, context="CREATE_MESSAGE_ERROR"
            )
            raise HTTPException(
                status_code=_http_status_for_unexpected_service_exception(e),
                detail=get_user_facing_error_message(e),
            ) from e

    def count_tokens(self, request_data: TokenCountRequest) -> TokenCountResponse:
        """Count tokens for a request after applying configured model routing."""
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        with logger.contextualize(request_id=request_id):
            try:
                _require_non_empty_messages(request_data.messages)
                routed = self._model_router.resolve_token_count_request(request_data)
                tokens = self._token_counter(
                    routed.request.messages, routed.request.system, routed.request.tools
                )
                logger.info(
                    "COUNT_TOKENS: request_id={} model={} messages={} input_tokens={}",
                    request_id,
                    routed.request.model,
                    len(routed.request.messages),
                    tokens,
                )
                return TokenCountResponse(input_tokens=tokens)
            except ProviderError:
                raise
            except Exception as e:
                _log_unexpected_service_exception(
                    self._settings,
                    e,
                    context="COUNT_TOKENS_ERROR",
                    request_id=request_id,
                )
                raise HTTPException(
                    status_code=_http_status_for_unexpected_service_exception(e),
                    detail=get_user_facing_error_message(e),
                ) from e
