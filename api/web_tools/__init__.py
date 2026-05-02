"""Submodules for Anthropic web server tool handling (search/fetch, egress, streaming)."""

from .egress import (
    WebFetchEgressPolicy,
    WebFetchEgressViolation,
    enforce_web_fetch_egress,
)
from .enrichment import enrich_empty_tool_results
from .request import (
    convert_server_tools_to_regular,
    has_agent_web_tools,
    has_listed_anthropic_server_tools,
    inject_web_search_system_prompt,
    is_web_server_tool_request,
    strip_server_tools,
)
from .streaming import (
    stream_web_server_tool_response,
    stream_with_web_tool_interception,
)

__all__ = [
    "WebFetchEgressPolicy",
    "WebFetchEgressViolation",
    "convert_server_tools_to_regular",
    "enrich_empty_tool_results",
    "enforce_web_fetch_egress",
    "has_agent_web_tools",
    "has_listed_anthropic_server_tools",
    "inject_web_search_system_prompt",
    "is_web_server_tool_request",
    "stream_web_server_tool_response",
    "stream_with_web_tool_interception",
    "strip_server_tools",
]
