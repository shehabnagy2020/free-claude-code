"""Detect forced Anthropic web server tool requests."""

from __future__ import annotations

from api.models.anthropic import MessagesRequest, Tool


def request_text(request: MessagesRequest) -> str:
    """Join all user/assistant message content into one string for tool input parsing."""
    from .parsers import content_text

    return "\n".join(content_text(message.content) for message in request.messages)


def forced_tool_turn_text(request: MessagesRequest) -> str:
    """Text for parsing forced server-tool inputs: latest user turn only (avoids stale history)."""
    if not request.messages:
        return ""

    from .parsers import content_text

    for message in reversed(request.messages):
        if message.role == "user":
            return content_text(message.content)
    return ""


def forced_server_tool_name(request: MessagesRequest) -> str | None:
    """Return web_search or web_fetch only when tool_choice forces that server tool."""
    tc = request.tool_choice
    if not isinstance(tc, dict):
        return None
    if tc.get("type") != "tool":
        return None
    name = tc.get("name")
    if name in {"web_search", "web_fetch"}:
        return str(name)
    return None


def has_tool_named(request: MessagesRequest, name: str) -> bool:
    return any(tool.name == name for tool in request.tools or [])


def is_web_server_tool_request(request: MessagesRequest) -> bool:
    """True when the client forces a web server tool via tool_choice (not merely listed)."""
    forced = forced_server_tool_name(request)
    if forced is None:
        return False
    return has_tool_named(request, forced)


def is_anthropic_server_tool_definition(tool: Tool) -> bool:
    """Whether ``tool`` refers to an Anthropic server tool (web_search / web_fetch family)."""
    name = (tool.name or "").strip()
    if name in ("web_search", "web_fetch"):
        return True
    typ = tool.type
    if isinstance(typ, str):
        return typ.startswith("web_search") or typ.startswith("web_fetch")
    return False


def has_listed_anthropic_server_tools(request: MessagesRequest) -> bool:
    """True when tools include web_search / web_fetch-style entries (listed, forced or not)."""
    return any(is_anthropic_server_tool_definition(t) for t in (request.tools or []))


def strip_server_tools(request: MessagesRequest) -> MessagesRequest:
    """Return a copy of *request* with Anthropic server tool definitions removed.

    Providers (NVIDIA NIM, OpenRouter, Ollama, etc.) do not support
    ``web_search`` / ``web_fetch`` tool definitions — those are handled
    proxy-side.  Stripping them prevents upstream 4xx errors and avoids
    leaking proxy implementation details to the provider.

    Also clears ``tool_choice`` when it was forcing one of the stripped tools,
    so the provider does not receive a ``tool_choice`` that references a
    non-existent tool.
    """
    tools = request.tools or []
    kept = [t for t in tools if not is_anthropic_server_tool_definition(t)]
    changed = len(kept) != len(tools)

    tc = request.tool_choice
    if tc and forced_server_tool_name(request) is not None:
        tc = None
        changed = True

    if not changed:
        return request

    data = request.model_dump()
    data["tools"] = [t.model_dump() for t in kept] if kept else None
    data["tool_choice"] = tc
    return MessagesRequest(**data)


def openai_chat_upstream_server_tool_error(
    request: MessagesRequest, *, web_tools_enabled: bool
) -> str | None:
    """Return a user-facing error when OpenAI Chat upstream cannot satisfy server-tool semantics.

    Only errors when tool_choice *forces* a server tool but web tools are disabled.
    Listed-but-not-forced server tools are silently stripped by strip_server_tools().
    """
    forced = forced_server_tool_name(request)
    if forced and not web_tools_enabled:
        return (
            f"tool_choice forces Anthropic server tool {forced!r}, but local web server tools are "
            "disabled (ENABLE_WEB_SERVER_TOOLS=false). "
            "Set TAVILY_MCP_URL and ENABLE_WEB_SERVER_TOOLS=true in your .env to enable them."
        )
    return None
