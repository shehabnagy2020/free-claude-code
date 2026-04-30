"""Detect and convert Anthropic web server tool requests."""

from __future__ import annotations

from typing import Any

from api.models.anthropic import MessagesRequest, Tool

_WEB_SEARCH_SYSTEM_INJECTION = (
    "\n\n<web_search_instruction>"
    "You have access to a real-time web search tool called WebSearch. "
    "Whenever the user asks about current events, live data, today's news, weather, "
    "prices, scores, or anything that may have changed recently, you MUST call the "
    "WebSearch tool with a relevant query to retrieve up-to-date information BEFORE answering. "
    "Do NOT rely solely on your training data for time-sensitive queries. "
    "Always use WebSearch for weather, news, prices, sports scores, and recent events."
    "</web_search_instruction>"
)

# Input schemas for converting server tools to regular tools.
_WEB_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query to look up on the web",
        },
    },
    "required": ["query"],
}

_WEB_FETCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch content from",
        },
    },
    "required": ["url"],
}

_SERVER_TOOL_BLOCK_TYPES = frozenset(
    {"server_tool_use", "web_search_tool_result", "web_fetch_tool_result"}
)


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


_AGENT_WEB_TOOL_NAMES = frozenset({"WebSearch", "WebFetch"})


def has_agent_web_tools(request: MessagesRequest) -> bool:
    """True when Claude Code agent tools WebSearch / WebFetch are in the tools list."""
    return any((t.name or "") in _AGENT_WEB_TOOL_NAMES for t in (request.tools or []))


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


def _server_tool_to_regular(tool: Tool) -> Tool:
    """Convert a single server tool definition to a regular tool definition."""
    name = (tool.name or "").strip()
    typ = tool.type or ""
    if name == "web_search" or (isinstance(typ, str) and typ.startswith("web_search")):
        return Tool(
            name="web_search",
            description="Search the web for current information. Returns titles, URLs, and snippets.",
            input_schema=_WEB_SEARCH_INPUT_SCHEMA,
        )
    if name == "web_fetch" or (isinstance(typ, str) and typ.startswith("web_fetch")):
        return Tool(
            name="web_fetch",
            description="Fetch and extract content from a web URL.",
            input_schema=_WEB_FETCH_INPUT_SCHEMA,
        )
    return tool


def convert_server_tools_to_regular(request: MessagesRequest) -> MessagesRequest:
    """Convert server tool definitions to regular tool definitions with input_schema.

    Also sanitizes message history to replace ``server_tool_use`` and
    ``web_search_tool_result`` / ``web_fetch_tool_result`` blocks with
    provider-compatible equivalents (``tool_use`` / ``text``).
    """
    tools = request.tools or []
    has_server_tools = any(is_anthropic_server_tool_definition(t) for t in tools)
    messages_dirty = _messages_contain_server_tool_blocks(request.messages)

    if not has_server_tools and not messages_dirty:
        return request

    data = request.model_dump()

    if has_server_tools:
        new_tools = [_server_tool_to_regular(t) for t in tools]
        data["tools"] = [t.model_dump() for t in new_tools]

    if messages_dirty:
        data["messages"] = [
            _sanitize_message_blocks(msg) for msg in data["messages"]
        ]

    return MessagesRequest(**data)


def _messages_contain_server_tool_blocks(messages: list[Any]) -> bool:
    """Check whether any message contains server_tool_use or result blocks."""
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            block_type = _block_type(block)
            if block_type in _SERVER_TOOL_BLOCK_TYPES:
                return True
    return False


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("type", ""))
    return str(getattr(block, "type", ""))


def _sanitize_message_blocks(message: dict[str, Any]) -> dict[str, Any]:
    """Replace server tool blocks with provider-compatible equivalents."""
    content = message.get("content")
    if not isinstance(content, list):
        return message

    new_content: list[Any] = []
    for block in content:
        bt = _block_type(block)
        if bt == "server_tool_use":
            # Convert to regular tool_use.
            new_content.append({
                "type": "tool_use",
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            })
        elif bt in ("web_search_tool_result", "web_fetch_tool_result"):
            # Convert to a text block summarising the result.
            result_content = block.get("content", "")
            summary = _summarise_tool_result(bt, result_content)
            new_content.append({"type": "text", "text": summary})
        else:
            new_content.append(block)

    return {**message, "content": new_content}


def _summarise_tool_result(block_type: str, content: Any) -> str:
    """Create a plain-text summary of a web_search/web_fetch result block."""
    if isinstance(content, list):
        # web_search_tool_result: list of {type, title, url, ...}
        parts = ["[Web search results]"]
        for item in content:
            if isinstance(item, dict):
                title = item.get("title", "")
                url = item.get("url", "")
                if title or url:
                    parts.append(f"- {title}: {url}")
        return "\n".join(parts) if len(parts) > 1 else "[Web search completed]"
    if isinstance(content, dict):
        # web_fetch_tool_result
        data = content.get("content", {})
        if isinstance(data, dict):
            source = data.get("source", {})
            if isinstance(source, dict):
                text = source.get("data", "")
                if text:
                    return f"[Fetched content]\n{text[:2000]}"
        return "[Web fetch completed]"
    return "[Web tool result]"


def openai_chat_upstream_server_tool_error(
    request: MessagesRequest, *, web_tools_enabled: bool
) -> str | None:
    """Return a user-facing error when OpenAI Chat upstream cannot satisfy server-tool semantics.

    Errors when:
    - ``tool_choice`` *forces* a server tool but web tools are disabled.
    - Server tools are *listed* (even without forced tool_choice) but web tools
      are disabled — OpenAI Chat upstreams cannot handle Anthropic server tools.
    """
    forced = forced_server_tool_name(request)
    if forced and not web_tools_enabled:
        return (
            f"tool_choice forces Anthropic server tool {forced!r}, but local web server tools are "
            "disabled (ENABLE_WEB_SERVER_TOOLS=false). "
            "Set TAVILY_MCP_URL and ENABLE_WEB_SERVER_TOOLS=true in your .env to enable them."
        )
    if has_listed_anthropic_server_tools(request) and not web_tools_enabled:
        return (
            "OpenAI Chat upstreams cannot handle Anthropic server tools (web_search / web_fetch). "
            "Set TAVILY_API_KEY and ENABLE_WEB_SERVER_TOOLS=true in your .env to enable them."
        )
    return None


def inject_web_search_system_prompt(request: MessagesRequest) -> MessagesRequest:
    """Append a web-search instruction to the system prompt.

    Forces the model to call web_search for real-time queries instead of
    reasoning its way to a training-data answer (especially with thinking enabled).
    No-ops if the instruction is already present (idempotent).
    """
    injection = _WEB_SEARCH_SYSTEM_INJECTION
    system = request.system

    # Already injected — skip.
    if isinstance(system, str) and injection.strip() in system:
        return request
    if isinstance(system, list) and any(
        isinstance(b, dict) and injection.strip() in b.get("text", "")
        for b in system
    ):
        return request

    data = request.model_dump()
    if system is None:
        data["system"] = injection.strip()
    elif isinstance(system, str):
        data["system"] = system + injection
    else:
        # List of SystemContent blocks — append a new text block.
        blocks = [b if isinstance(b, dict) else b.model_dump() for b in system]
        blocks.append({"type": "text", "text": injection.strip()})
        data["system"] = blocks

    return MessagesRequest(**data)
