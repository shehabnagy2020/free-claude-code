from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import api.web_tools.constants as web_tool_constants
from api.model_router import ModelRouter, ResolvedModel, RoutedMessagesRequest
from api.models.anthropic import Message, MessagesRequest, Tool
from api.services import ClaudeProxyService
from api.web_tools import egress as web_egress
from api.web_tools.egress import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    enforce_web_fetch_egress,
)
from api.web_tools.outbound import (
    _drain_response_body_capped,
    _read_response_body_capped,
    _run_web_fetch,
)
from api.web_tools.request import is_web_server_tool_request
from api.web_tools.streaming import stream_web_server_tool_response
from config.settings import Settings
from core.anthropic.stream_contracts import (
    assert_anthropic_stream_contract,
    parse_sse_text,
    text_content,
)
from messaging.event_parser import parse_cli_event
from providers.exceptions import InvalidRequestError

_STRICT_EGRESS = WebFetchEgressPolicy(
    allow_private_network_targets=False,
    allowed_schemes=frozenset({"http", "https"}),
)


class FixedProviderModelRouter(ModelRouter):
    """Test double: pin ``provider_id`` for OpenAI vs native routing assertions."""

    def __init__(self, settings: Settings, provider_id: str) -> None:
        super().__init__(settings)
        self._fixed_provider_id = provider_id

    def resolve_messages_request(
        self, request: MessagesRequest
    ) -> RoutedMessagesRequest:
        resolved = ResolvedModel(
            original_model=request.model,
            provider_id=self._fixed_provider_id,
            provider_model=request.model,
            provider_model_ref=f"{self._fixed_provider_id}/{request.model}",
            thinking_enabled=False,
        )
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(request=routed, resolved=resolved)


def test_web_server_tool_not_detected_when_tool_only_listed():
    """Listing web_search without forcing it must not skip the upstream provider."""
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[Message(role="user", content="search")],
        tools=[Tool(name="web_search", type="web_search_20250305")],
    )

    assert not is_web_server_tool_request(request)


def test_web_server_tool_detected_when_tool_choice_forces_it():
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[Message(role="user", content="search")],
        tools=[Tool(name="web_search", type="web_search_20250305")],
        tool_choice={"type": "tool", "name": "web_search"},
    )

    assert is_web_server_tool_request(request)


def test_web_server_tool_not_detected_when_forced_name_missing_from_tools():
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[Message(role="user", content="hi")],
        tools=[Tool(name="other", type="function")],
        tool_choice={"type": "tool", "name": "web_search"},
    )

    assert not is_web_server_tool_request(request)


def test_service_rejects_forced_server_tool_on_openai_when_disabled():
    """OpenAI Chat upstreams cannot run forced server tools without the local handler."""
    settings = Settings()
    assert settings.enable_web_server_tools is False
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: MagicMock(),
        model_router=FixedProviderModelRouter(settings, "nvidia_nim"),
    )
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            Message(
                role="user",
                content="Perform a web search for the query: DeepSeek V4 model release 2026",
            )
        ],
        tools=[Tool(name="web_search", type="web_search_20250305")],
        tool_choice={"type": "tool", "name": "web_search"},
    )
    with pytest.raises(InvalidRequestError, match="ENABLE_WEB_SERVER_TOOLS"):
        service.create_message(request)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://192.168.1.1/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://localhost/foo",
        "http://mybox.local/",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_enforce_web_fetch_egress_blocks_internal_or_disallowed(url: str):
    with pytest.raises(WebFetchEgressViolation):
        enforce_web_fetch_egress(url, _STRICT_EGRESS)


def test_enforce_web_fetch_egress_allows_global_literal_ip():
    enforce_web_fetch_egress("http://8.8.8.8/", _STRICT_EGRESS)


def test_enforce_web_fetch_egress_skips_private_checks_when_opted_in():
    enforce_web_fetch_egress(
        "http://127.0.0.1/",
        WebFetchEgressPolicy(
            allow_private_network_targets=True,
            allowed_schemes=frozenset({"http", "https"}),
        ),
    )


def _cm(mock_client: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _stream_cm(response: httpx.Response) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _aiohttp_response(
    status: int,
    *,
    url: str = "http://8.8.8.8/",
    location: str | None = None,
    body: bytes = b"hello world",
) -> MagicMock:
    r = MagicMock()
    r.status = status
    r.url = url
    hdrs: dict[str, str] = {}
    if location is not None:
        hdrs["location"] = location
    r.headers = hdrs
    r.get_encoding = MagicMock(return_value="utf-8")
    r.raise_for_status = MagicMock()
    r.request_info = MagicMock()
    r.history = ()

    async def iter_chunked(_n: int) -> Any:
        yield body

    r.content.iter_chunked = MagicMock(side_effect=iter_chunked)
    return r


def _aiohttp_client_session_patch(
    *responses: MagicMock,
) -> tuple[MagicMock, MagicMock]:
    """Build ``ClientSession`` mock that serves ``responses`` to successive ``get`` calls."""
    queue = list(responses)
    n = 0

    def get_side(*_a: Any, **_k: Any) -> Any:
        nonlocal n
        resp = queue[n] if n < len(queue) else queue[-1]
        n += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    session = MagicMock()
    session.get = MagicMock(side_effect=get_side)

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=session)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    return client_cm, session


def test_enforce_web_fetch_egress_documents_connect_time_pinning():
    assert enforce_web_fetch_egress.__doc__ and "resolved addresses" in (
        enforce_web_fetch_egress.__doc__ or ""
    )
    assert (
        web_egress.get_validated_stream_addrinfos_for_egress.__doc__
        and "pinning"
        in (web_egress.get_validated_stream_addrinfos_for_egress.__doc__ or "")
    )
    assert "DNS-pinned" in (_run_web_fetch.__doc__ or "")


@pytest.mark.asyncio
async def test_run_web_fetch_follows_redirect_when_each_hop_is_allowed():
    res_redirect = _aiohttp_response(
        302, url="http://8.8.8.8/start", location="/final", body=b""
    )
    res_ok = _aiohttp_response(200, url="http://8.8.8.8/final", body=b"hello world")
    client_cm, session = _aiohttp_client_session_patch(res_redirect, res_ok)
    with patch("api.web_tools.outbound.ClientSession", return_value=client_cm):
        out = await _run_web_fetch("http://8.8.8.8/start", _STRICT_EGRESS)

    assert out["data"] == "hello world"
    assert session.get.call_count == 2


@pytest.mark.asyncio
async def test_run_web_fetch_truncates_large_body_to_byte_cap(monkeypatch):
    huge = b"x" * 5000
    res_ok = _aiohttp_response(200, url="http://8.8.8.8/big", body=huge)
    client_cm, _ = _aiohttp_client_session_patch(res_ok)
    monkeypatch.setattr(web_tool_constants, "_MAX_WEB_FETCH_RESPONSE_BYTES", 100)
    with patch("api.web_tools.outbound.ClientSession", return_value=client_cm):
        out = await _run_web_fetch("http://8.8.8.8/big", _STRICT_EGRESS)

    assert len(out["data"]) <= 100
    assert out["data"] == "x" * 100


@pytest.mark.asyncio
async def test_run_web_fetch_redirect_to_blocked_host_raises():
    res_redirect = _aiohttp_response(
        302,
        url="http://8.8.8.8/start",
        location="http://127.0.0.1/secret",
        body=b"",
    )
    client_cm, session = _aiohttp_client_session_patch(res_redirect)
    with (
        patch("api.web_tools.outbound.ClientSession", return_value=client_cm),
        pytest.raises(WebFetchEgressViolation),
    ):
        await _run_web_fetch("http://8.8.8.8/start", _STRICT_EGRESS)

    session.get.assert_called_once()


@pytest.mark.asyncio
async def test_run_web_fetch_redirect_without_location_raises():
    res_bad = _aiohttp_response(302, url="http://8.8.8.8/here", body=b"")
    client_cm, _ = _aiohttp_client_session_patch(res_bad)
    with (
        patch("api.web_tools.outbound.ClientSession", return_value=client_cm),
        pytest.raises(WebFetchEgressViolation, match="missing Location"),
    ):
        await _run_web_fetch("http://8.8.8.8/here", _STRICT_EGRESS)


@pytest.mark.asyncio
async def test_run_web_fetch_excess_redirects_raises():
    res1 = _aiohttp_response(302, url="http://8.8.8.8/a", location="/b", body=b"")
    res2 = _aiohttp_response(302, url="http://8.8.8.8/b", location="/c", body=b"")
    client_cm, _ = _aiohttp_client_session_patch(res1, res2)
    with (
        patch("api.web_tools.constants._MAX_WEB_FETCH_REDIRECTS", 1),
        patch("api.web_tools.outbound.ClientSession", return_value=client_cm),
        pytest.raises(WebFetchEgressViolation, match="exceeded maximum redirects"),
    ):
        await _run_web_fetch("http://8.8.8.8/a", _STRICT_EGRESS)


@pytest.mark.asyncio
async def test_streams_web_search_server_tool_result(monkeypatch):
    async def fake_search(_api_key: str, query: str) -> list[dict[str, str]]:
        assert query == "DeepSeek V4 model release 2026"
        return [{"title": "DeepSeek V4 Released", "url": "https://example.com/v4"}]

    monkeypatch.setattr("api.web_tools.tavily.tavily_search", fake_search)
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            Message(
                role="user",
                content=(
                    "Perform a web search for the query: DeepSeek V4 model release 2026"
                ),
            )
        ],
        tools=[Tool(name="web_search", type="web_search_20250305")],
        tool_choice={"type": "tool", "name": "web_search"},
    )

    raw = "".join(
        [
            event
            async for event in stream_web_server_tool_response(
                request,
                input_tokens=42,
                web_fetch_egress=_STRICT_EGRESS,
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)
    starts = [e for e in events if e.event == "content_block_start"]
    assert starts[0].data["content_block"]["type"] == "server_tool_use"
    assert starts[0].data["content_block"]["name"] == "web_search"
    tool_use_id = starts[0].data["content_block"]["id"]
    assert starts[1].data["content_block"]["type"] == "web_search_tool_result"
    assert starts[1].data["content_block"]["tool_use_id"] == tool_use_id
    assert starts[1].data["content_block"]["content"][0]["url"] == (
        "https://example.com/v4"
    )
    text_deltas = [
        e
        for e in events
        if e.event == "content_block_delta"
        and e.data.get("delta", {}).get("type") == "text_delta"
    ]
    assert text_deltas, "summary must be streamed as text_delta"
    assert "example.com" in text_content(events)
    cli_text: list[str] = []
    for ev in events:
        cli_text.extend(
            str(p.get("text", ""))
            for p in parse_cli_event(ev.data)
            if p.get("type") == "text_delta"
        )
    assert "example.com" in "".join(cli_text)
    deltas = [e for e in events if e.event == "message_delta"]
    assert deltas[-1].data["usage"]["server_tool_use"] == {"web_search_requests": 1}


@pytest.mark.asyncio
async def test_forced_web_fetch_ignores_stale_url_from_prior_user_turns(monkeypatch):
    """Only the latest user message supplies the URL (not earlier transcript text)."""
    target = "https://new-only.example.com/page"

    async def fake_fetch(_api_key: str, url: str) -> dict[str, str]:
        assert url == target
        return {
            "url": url,
            "title": "T",
            "media_type": "text/plain",
            "data": "x",
        }

    monkeypatch.setattr("api.web_tools.tavily.tavily_fetch", fake_fetch)
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            Message(
                role="user",
                content="Earlier turn https://stale.com/old-article ignore this",
            ),
            Message(role="assistant", content="ok"),
            Message(
                role="user",
                content=f"Please fetch {target} for the summary",
            ),
        ],
        tools=[Tool(name="web_fetch", type="web_fetch_20250910")],
        tool_choice={"type": "tool", "name": "web_fetch"},
    )

    raw = "".join(
        [
            event
            async for event in stream_web_server_tool_response(
                request,
                input_tokens=1,
                web_fetch_egress=_STRICT_EGRESS,
                tavily_api_key="tvly-test",
            )
        ]
    )
    assert target in raw


@pytest.mark.asyncio
async def test_streams_web_fetch_server_tool_result(monkeypatch):
    async def fake_fetch(_api_key: str, url: str) -> dict[str, str]:
        assert url == "https://example.com/article"
        return {
            "url": url,
            "title": "Example Article",
            "media_type": "text/plain",
            "data": "Article body",
        }

    monkeypatch.setattr("api.web_tools.tavily.tavily_fetch", fake_fetch)
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            Message(role="user", content="Fetch https://example.com/article please")
        ],
        tools=[Tool(name="web_fetch", type="web_fetch_20250910")],
        tool_choice={"type": "tool", "name": "web_fetch"},
    )

    raw = "".join(
        [
            event
            async for event in stream_web_server_tool_response(
                request,
                input_tokens=42,
                web_fetch_egress=_STRICT_EGRESS,
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)
    starts = [e for e in events if e.event == "content_block_start"]
    assert starts[0].data["content_block"]["type"] == "server_tool_use"
    tool_use_id = starts[0].data["content_block"]["id"]
    assert starts[1].data["content_block"]["type"] == "web_fetch_tool_result"
    assert starts[1].data["content_block"]["tool_use_id"] == tool_use_id
    assert starts[1].data["content_block"]["content"]["content"]["title"] == (
        "Example Article"
    )
    assert any(
        e.event == "content_block_delta"
        and e.data.get("delta", {}).get("type") == "text_delta"
        for e in events
    )
    assert "Article body" in text_content(events)
    cli_text: list[str] = []
    for ev in events:
        cli_text.extend(
            str(p.get("text", ""))
            for p in parse_cli_event(ev.data)
            if p.get("type") == "text_delta"
        )
    assert "Article body" in "".join(cli_text)
    deltas = [e for e in events if e.event == "message_delta"]
    assert deltas[-1].data["usage"]["server_tool_use"] == {"web_fetch_requests": 1}


@pytest.mark.asyncio
async def test_streams_web_fetch_error_summary_generic_by_default(monkeypatch):
    secret = "sensitive-upstream-token"

    async def boom(_api_key: str, _url: str) -> dict[str, str]:
        raise ValueError(secret)

    monkeypatch.setattr("api.web_tools.tavily.tavily_fetch", boom)
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[
            Message(
                role="user",
                content="Fetch https://example.com/sensitive-path?x=1 please",
            )
        ],
        tools=[Tool(name="web_fetch", type="web_fetch_20250910")],
        tool_choice={"type": "tool", "name": "web_fetch"},
    )

    with patch("api.web_tools.outbound.logger.warning") as log_warn:
        raw = "".join(
            [
                event
                async for event in stream_web_server_tool_response(
                    request,
                    input_tokens=1,
                    web_fetch_egress=_STRICT_EGRESS,
                    verbose_client_errors=False,
                    tavily_api_key="tvly-test",
                )
            ]
        )

    assert secret not in raw
    assert "ValueError" not in raw
    assert "Web tool request failed." in raw
    err_events = parse_sse_text(raw)
    assert_anthropic_stream_contract(err_events)
    assert any(
        e.event == "content_block_delta"
        and e.data.get("delta", {}).get("type") == "text_delta"
        for e in err_events
    )
    cli_err_text: list[str] = []
    for ev in err_events:
        cli_err_text.extend(
            str(p.get("text", ""))
            for p in parse_cli_event(ev.data)
            if p.get("type") == "text_delta"
        )
    assert "Web tool request failed." in "".join(cli_err_text)
    log_blob = " ".join(str(a) for c in log_warn.call_args_list for a in c.args)
    assert secret not in log_blob
    assert "example.com" in log_blob
    assert "/sensitive-path" not in log_blob


@pytest.mark.asyncio
async def test_streams_web_fetch_error_summary_verbose_includes_exception_class(
    monkeypatch,
):
    async def boom(_api_key: str, _url: str) -> dict[str, str]:
        raise OSError(5, "oops")

    monkeypatch.setattr("api.web_tools.tavily.tavily_fetch", boom)
    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[Message(role="user", content="Fetch https://example.com/x")],
        tools=[Tool(name="web_fetch", type="web_fetch_20250910")],
        tool_choice={"type": "tool", "name": "web_fetch"},
    )

    raw = "".join(
        [
            event
            async for event in stream_web_server_tool_response(
                request,
                input_tokens=1,
                web_fetch_egress=_STRICT_EGRESS,
                verbose_client_errors=True,
                tavily_api_key="tvly-test",
            )
        ]
    )
    assert "OSError" in raw


@pytest.mark.asyncio
async def test_read_response_body_capped_truncates_single_oversized_chunk():
    cap = 500

    async def aiter_bytes(chunk_size=None):
        yield b"z" * (cap * 20)

    response = MagicMock()
    response.aiter_bytes = aiter_bytes

    out = await _read_response_body_capped(response, cap)
    assert len(out) == cap
    assert out == b"z" * cap


@pytest.mark.asyncio
async def test_drain_response_body_capped_stops_after_first_chunk_when_oversized():
    cap = 300
    chunk_calls = {"n": 0}

    async def aiter_bytes(chunk_size=None):
        chunk_calls["n"] += 1
        yield b"y" * (cap * 10)

    response = MagicMock()
    response.aiter_bytes = aiter_bytes

    await _drain_response_body_capped(response, cap)
    assert chunk_calls["n"] == 1


def test_service_rejects_listed_server_tools_on_openai_chat() -> None:
    settings = Settings()
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: MagicMock(),
        model_router=FixedProviderModelRouter(settings, "nvidia_nim"),
    )
    request = MessagesRequest(
        model="m",
        max_tokens=20,
        messages=[Message(role="user", content="q")],
        tools=[Tool(name="web_search", type="web_search_20250305")],
    )
    with pytest.raises(InvalidRequestError, match="OpenAI Chat upstreams"):
        service.create_message(request)


def test_listed_server_tools_routed_on_open_router() -> None:
    """Native Anthropic transport may receive listed server tool definitions."""
    settings = Settings()

    async def fake_stream(*_a, **_k):
        yield 'event: message_start\ndata: {"type":"message_start"}\n\n'
        yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'

    mock_provider = MagicMock()
    mock_provider.stream_response = fake_stream
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: mock_provider,
        model_router=FixedProviderModelRouter(settings, "open_router"),
    )
    request = MessagesRequest(
        model="m",
        max_tokens=20,
        messages=[Message(role="user", content="q")],
        tools=[Tool(name="web_search", type="web_search_20250305")],
    )
    service.create_message(request)
    mock_provider.preflight_stream.assert_called()


# ---------------------------------------------------------------------------
# convert_server_tools_to_regular
# ---------------------------------------------------------------------------


def test_convert_server_tools_to_regular_converts_web_search():
    from api.web_tools.request import convert_server_tools_to_regular

    request = MessagesRequest(
        model="m",
        max_tokens=20,
        messages=[Message(role="user", content="q")],
        tools=[
            Tool(name="web_search", type="web_search_20250305"),
            Tool(
                name="bash",
                description="Run bash",
                input_schema={"type": "object", "properties": {}},
            ),
        ],
    )
    converted = convert_server_tools_to_regular(request)
    assert converted.tools is not None
    assert len(converted.tools) == 2
    ws = converted.tools[0]
    assert ws.name == "web_search"
    assert ws.type is None  # no longer a server tool type
    assert ws.input_schema is not None
    assert "query" in ws.input_schema.get("properties", {})
    # non-server tool unchanged
    assert converted.tools[1].name == "bash"


def test_convert_server_tools_to_regular_converts_web_fetch():
    from api.web_tools.request import convert_server_tools_to_regular

    request = MessagesRequest(
        model="m",
        max_tokens=20,
        messages=[Message(role="user", content="q")],
        tools=[Tool(name="web_fetch", type="web_fetch_20250910")],
    )
    converted = convert_server_tools_to_regular(request)
    assert converted.tools is not None
    wf = converted.tools[0]
    assert wf.name == "web_fetch"
    assert wf.input_schema is not None
    assert "url" in wf.input_schema.get("properties", {})


def test_convert_server_tools_sanitises_message_history():
    from api.web_tools.request import convert_server_tools_to_regular

    request = MessagesRequest(
        model="m",
        max_tokens=20,
        messages=[
            Message(role="user", content="search for X"),
            Message(
                role="assistant",
                content=[
                    {
                        "type": "server_tool_use",
                        "id": "srvtoolu_123",
                        "name": "web_search",
                        "input": {"query": "X"},
                    },
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srvtoolu_123",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Result",
                                "url": "https://example.com",
                            }
                        ],
                    },
                    {"type": "text", "text": "Here are the results."},
                ],
            ),
            Message(role="user", content="thanks"),
        ],
        tools=[Tool(name="web_search", type="web_search_20250305")],
    )
    converted = convert_server_tools_to_regular(request)
    # assistant message should have tool_use instead of server_tool_use
    assistant_msg = converted.messages[1]
    blocks = assistant_msg.content
    assert isinstance(blocks, list)
    assert blocks[0]["type"] == "tool_use"
    assert blocks[0]["name"] == "web_search"
    # web_search_tool_result → text block
    assert blocks[1]["type"] == "text"
    assert "Result" in blocks[1]["text"]
    # original text block unchanged
    assert blocks[2]["type"] == "text"


# ---------------------------------------------------------------------------
# stream_with_web_tool_interception
# ---------------------------------------------------------------------------


def _build_provider_sse_stream(
    *tool_calls: tuple[str, dict],
    text_before: str = "",
) -> list[str]:
    """Build a minimal SSE stream from a provider that may include tool_use blocks."""
    import json

    events: list[str] = []
    events.append(
        f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'content': [], 'model': 'm', 'stop_reason': None, 'usage': {'input_tokens': 10, 'output_tokens': 1}}})}\n\n"
    )
    idx = 0
    if text_before:
        events.append(
            f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
        )
        events.append(
            f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'text_delta', 'text': text_before}})}\n\n"
        )
        events.append(
            f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': idx})}\n\n"
        )
        idx += 1

    has_tool_use = len(tool_calls) > 0
    for tool_name, tool_input in tool_calls:
        tool_id = f"toolu_{idx}"
        events.append(
            f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': idx, 'content_block': {'type': 'tool_use', 'id': tool_id, 'name': tool_name, 'input': {}}})}\n\n"
        )
        events.append(
            f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': idx, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(tool_input)}})}\n\n"
        )
        events.append(
            f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': idx})}\n\n"
        )
        idx += 1

    stop_reason = "tool_use" if has_tool_use else "end_turn"
    events.append(
        f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop_reason}, 'usage': {'output_tokens': 10}})}\n\n"
    )
    events.append(
        f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
    )
    return events


@pytest.mark.asyncio
async def test_interception_converts_web_search_to_server_tool_use(monkeypatch):
    from api.web_tools.streaming import stream_with_web_tool_interception

    async def fake_search(_api_key: str, query: str) -> list[dict[str, str]]:
        return [
            {
                "title": "Weather Cairo",
                "url": "https://weather.com/cairo",
                "snippet": "Sunny 35C",
            }
        ]

    monkeypatch.setattr("api.web_tools.tavily.tavily_search", fake_search)

    provider_events = _build_provider_sse_stream(
        ("web_search", {"query": "Cairo weather"}),
    )

    async def fake_provider_stream():
        for ev in provider_events:
            yield ev

    raw = "".join(
        [
            event
            async for event in stream_with_web_tool_interception(
                fake_provider_stream(),
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)

    starts = [e for e in events if e.event == "content_block_start"]
    # Should be: server_tool_use, web_search_tool_result, text
    assert len(starts) == 3
    assert starts[0].data["content_block"]["type"] == "server_tool_use"
    assert starts[0].data["content_block"]["name"] == "web_search"
    assert starts[0].data["content_block"]["input"] == {"query": "Cairo weather"}
    assert starts[1].data["content_block"]["type"] == "web_search_tool_result"
    assert (
        starts[1].data["content_block"]["content"][0]["url"]
        == "https://weather.com/cairo"
    )
    assert starts[2].data["content_block"]["type"] == "text"

    # stop_reason should be end_turn (not tool_use)
    deltas = [e for e in events if e.event == "message_delta"]
    assert deltas[-1].data["delta"]["stop_reason"] == "end_turn"

    # Summary text should mention weather
    assert "weather.com" in text_content(events).lower()


@pytest.mark.asyncio
async def test_interception_passes_through_non_web_search_tool_use():
    """tool_use for non-web tools should pass through unchanged."""
    from api.web_tools.streaming import stream_with_web_tool_interception

    provider_events = _build_provider_sse_stream(
        ("bash", {"command": "ls"}),
    )

    async def fake_provider_stream():
        for ev in provider_events:
            yield ev

    raw = "".join(
        [
            event
            async for event in stream_with_web_tool_interception(
                fake_provider_stream(),
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)

    starts = [e for e in events if e.event == "content_block_start"]
    assert len(starts) == 1
    assert starts[0].data["content_block"]["type"] == "tool_use"
    assert starts[0].data["content_block"]["name"] == "bash"

    # stop_reason should remain tool_use
    deltas = [e for e in events if e.event == "message_delta"]
    assert deltas[-1].data["delta"]["stop_reason"] == "tool_use"


@pytest.mark.asyncio
async def test_interception_with_text_before_web_search(monkeypatch):
    """Text blocks before web_search should pass through, then web_search is intercepted."""
    from api.web_tools.streaming import stream_with_web_tool_interception

    async def fake_search(_api_key: str, query: str) -> list[dict[str, str]]:
        return [{"title": "Result", "url": "https://example.com", "snippet": "content"}]

    monkeypatch.setattr("api.web_tools.tavily.tavily_search", fake_search)

    provider_events = _build_provider_sse_stream(
        ("web_search", {"query": "test"}),
        text_before="I'll search for that.",
    )

    async def fake_provider_stream():
        for ev in provider_events:
            yield ev

    raw = "".join(
        [
            event
            async for event in stream_with_web_tool_interception(
                fake_provider_stream(),
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)

    starts = [e for e in events if e.event == "content_block_start"]
    # text + server_tool_use + web_search_tool_result + summary text = 4
    assert len(starts) == 4
    assert starts[0].data["content_block"]["type"] == "text"
    assert starts[1].data["content_block"]["type"] == "server_tool_use"
    assert starts[2].data["content_block"]["type"] == "web_search_tool_result"
    assert starts[3].data["content_block"]["type"] == "text"

    # Verify pre-search text is included
    assert "I'll search for that." in text_content(events)


@pytest.mark.asyncio
async def test_interception_handles_tavily_error_gracefully(monkeypatch):
    """When Tavily fails, error result and generic summary are emitted."""
    from api.web_tools.streaming import stream_with_web_tool_interception

    async def boom(_api_key: str, _query: str) -> list[dict[str, str]]:
        raise RuntimeError("Tavily API down")

    monkeypatch.setattr("api.web_tools.tavily.tavily_search", boom)

    provider_events = _build_provider_sse_stream(
        ("web_search", {"query": "test"}),
    )

    async def fake_provider_stream():
        for ev in provider_events:
            yield ev

    raw = "".join(
        [
            event
            async for event in stream_with_web_tool_interception(
                fake_provider_stream(),
                tavily_api_key="tvly-test",
            )
        ]
    )
    events = parse_sse_text(raw)
    assert_anthropic_stream_contract(events)

    starts = [e for e in events if e.event == "content_block_start"]
    assert starts[0].data["content_block"]["type"] == "server_tool_use"
    # Result should contain an error
    result_block = starts[1].data["content_block"]
    assert result_block["type"] == "web_search_tool_result"
    assert result_block["content"]["type"] == "web_search_tool_result_error"


@pytest.mark.asyncio
async def test_interception_no_tool_use_passes_through():
    """Stream without any tool_use should pass through completely unchanged."""
    from api.web_tools.streaming import stream_with_web_tool_interception

    provider_events = _build_provider_sse_stream(text_before="Hello world")

    async def fake_provider_stream():
        for ev in provider_events:
            yield ev

    raw_original = "".join(provider_events)
    raw_intercepted = "".join(
        [
            event
            async for event in stream_with_web_tool_interception(
                fake_provider_stream(),
                tavily_api_key="tvly-test",
            )
        ]
    )
    # Should be exactly the same
    assert raw_original == raw_intercepted
