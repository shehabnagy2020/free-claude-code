"""Web UI API routes – auth, sessions, messages, streaming chat proxy."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from config.settings import get_settings

from .dependencies import resolve_provider
from .models.anthropic import MessagesRequest
from .services import ClaudeProxyService
from .web_tools.tavily import tavily_fetch as _tavily_fetch
from .web_tools.tavily import tavily_search as _tavily_search
from .ui_db import UIChatDB

ui_router = APIRouter(prefix="/ui/api")


# ── Stateless HMAC token ──────────────────────────────────────────────────────────
#
# A token is HMAC-SHA256(password, key=password + ":fcc-ui").
# This is deterministic and survives server restarts without any stored state.

_TOKEN_SUFFIX = b":fcc-ui"


def _make_token(password: str) -> str:
    key = password.encode() + _TOKEN_SUFFIX
    return hmac.new(key, password.encode(), hashlib.sha256).hexdigest()


def _verify_token_value(token: str) -> bool:
    """Re-derive expected token from current password and compare in constant time."""
    settings = get_settings()
    expected = _make_token(settings.ui_password)
    return hmac.compare_digest(expected, token)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_db(request: Request) -> UIChatDB:
    return request.app.state.ui_db  # type: ignore[attr-defined]


def _verify_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token or not _verify_token_value(token):
        raise HTTPException(status_code=401, detail="Unauthorized – please log in")
    return token


Token = Annotated[str, Depends(_verify_token)]
DB = Annotated[UIChatDB, Depends(_get_db)]


# ── Request / response models ─────────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"
    model: str = "claude-opus-4-20250514"


class UpdateSessionRequest(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    content: str
    images: list[dict[str, str]] = []  # [{media_type, data}, ...] base64 image blocks
    model: str = "claude-opus-4-20250514"
    max_tokens: int = 8192


# ── Public endpoints (no auth) ────────────────────────────────────────────────


@ui_router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@ui_router.post("/auth/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    settings = get_settings()
    if body.password != settings.ui_password:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": _make_token(body.password)}


@ui_router.post("/auth/logout")
async def logout(request: Request) -> dict[str, bool]:
    # Stateless tokens – nothing to invalidate server-side.
    # Client is responsible for discarding the token.
    return {"ok": True}


# ── Config ────────────────────────────────────────────────────────────────────


# The three tiers always shown in the model selector, regardless of .env.
# The proxy's own resolve_model() maps each Claude ID to the right provider.
_MODEL_TIERS: list[dict[str, str]] = [
    {"label": "Claude Opus",   "claude_id": "claude-opus-4-20250514",     "tier": "opus"},
    {"label": "Claude Sonnet", "claude_id": "claude-3-5-sonnet-20241022", "tier": "sonnet"},
    {"label": "Claude Haiku",  "claude_id": "claude-3-haiku-20240307",    "tier": "haiku"},
]


def _provider_display(model_str: str) -> str:
    """Convert 'provider_type/model/name' → human-readable provider label."""
    if not model_str:
        return ""
    parts = model_str.split("/", 1)
    provider_id = parts[0]
    model_name = parts[1] if len(parts) > 1 else ""
    provider_label = provider_id.replace("_", " ").title()
    return f"{provider_label} › {model_name}" if model_name else provider_label


@ui_router.get("/config")
async def get_config(_: Token) -> dict[str, Any]:
    """Return the fixed three-tier model selector with resolved provider labels."""
    settings = get_settings()

    # Mark the tier that matches settings.model as default.
    default_tier = "opus"
    if settings.model:
        m = settings.model.lower()
        if "haiku" in m:
            default_tier = "haiku"
        elif "sonnet" in m:
            default_tier = "sonnet"

    models: list[dict[str, Any]] = []
    for tier in _MODEL_TIERS:
        resolved = settings.resolve_model(tier["claude_id"])
        models.append(
            {
                "label": tier["label"],
                "claude_model": tier["claude_id"],
                "provider_display": _provider_display(resolved),
                "is_default": tier["tier"] == default_tier,
            }
        )

    return {"models": models}


# ── Sessions ──────────────────────────────────────────────────────────────────


@ui_router.get("/sessions")
async def list_sessions(_: Token, db: DB) -> list[dict[str, Any]]:
    return await db.list_sessions()


@ui_router.post("/sessions", status_code=201)
async def create_session(body: CreateSessionRequest, _: Token, db: DB) -> dict[str, Any]:
    return await db.create_session(body.title, body.model)


@ui_router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str, body: UpdateSessionRequest, _: Token, db: DB
) -> dict[str, Any]:
    updated = await db.update_session(session_id, title=body.title)
    if updated is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return updated


@ui_router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: Token, db: DB) -> dict[str, bool]:
    deleted = await db.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@ui_router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, _: Token, db: DB) -> list[dict[str, Any]]:
    if not await db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return await db.get_messages(session_id)


# ── Streaming chat proxy ───────────────────────────────────────────────────────


@ui_router.post("/chat")
async def chat(body: ChatRequest, request: Request, _: Token, db: DB) -> StreamingResponse:
    """
    Stream a response from the provider in-process (no HTTP loopback).
    Saves user + assistant messages to the DB around the stream.
    """
    # Single DB round-trip: session check + history fetch combined
    history = await db.get_history_for_chat(body.session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build user content for API and DB
    if body.images:
        user_blocks: list[dict[str, Any]] = []
        for img in body.images:
            user_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/jpeg"),
                    "data": img["data"],
                },
            })
        if body.content.strip():
            user_blocks.append({"type": "text", "text": body.content})
        user_content_for_api: list[dict[str, Any]] | str = user_blocks
        user_content_for_db = json.dumps(user_blocks)
    else:
        user_content_for_api = body.content
        user_content_for_db = body.content

    # Save user message. Also bumps sessions.updated_at.
    await db.add_message(body.session_id, "user", user_content_for_db)

    # Auto-title: set on the first user turn so the sidebar updates immediately,
    # before the stream starts (no race with the finally block).
    user_text_for_title = body.content.strip() or "🖼️ Image"
    if not history:  # first message in this session
        new_title = user_text_for_title[:60].replace("\n", " ")
        if len(user_text_for_title) > 60:
            new_title += "…"
        await db.update_session(body.session_id, title=new_title)

    # Build messages list: prior history + new user turn (no extra DB fetch needed)
    def _parse_content(raw: str) -> list[dict[str, Any]] | str:
        if raw.startswith("["):
            try:
                return json.loads(raw)  # type: ignore[return-value]
            except json.JSONDecodeError:
                pass
        return raw

    api_messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": _parse_content(m["content"])} for m in history
    ]
    api_messages.append({"role": "user", "content": user_content_for_api})

    # Build the MessagesRequest and call the service in-process (no HTTP loopback)
    settings = get_settings()

    # Inject web_search / web_fetch tools when Tavily is configured so the model
    # can use them naturally without the caller forcing tool_choice.
    _WEB_TOOLS: list[dict[str, Any]] = [
        {
            "name": "web_search",
            "type": "custom",
            "description": (
                "Search the web for current information such as news, weather, prices, "
                "events, or anything that may have changed after your knowledge cutoff."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "web_fetch",
            "type": "custom",
            "description": "Fetch and read the full content of a URL.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch."},
                },
                "required": ["url"],
            },
        },
    ]
    injected_tools = _WEB_TOOLS if settings.tavily_api_key else None

    service = ClaudeProxyService(
        settings,
        provider_getter=lambda pt: resolve_provider(pt, app=request.app, settings=settings),
    )

    session_id = body.session_id
    # Keep a mutable reference to the current messages list so the agentic loop
    # can append tool_result turns without touching the outer api_messages list.
    loop_messages: list[dict[str, Any]] = list(api_messages)

    async def _collect_response(
        it: AsyncIterator[str],
    ) -> tuple[list[str], list[str], str | None, dict[str, Any] | None]:
        """Drain *it*, return (chunks, text_parts, tool_name, tool_input)."""
        chunks: list[str] = []
        text_parts: list[str] = []
        tool_name: str | None = None
        tool_input_parts: list[str] = []
        current_tool_block_index: int | None = None

        async for chunk in it:
            chunks.append(chunk)
            for line in chunk.splitlines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                try:
                    evt = json.loads(data_str)
                    etype = evt.get("type")
                    if etype == "content_block_start":
                        cb = evt.get("content_block", {})
                        if cb.get("type") == "tool_use" and cb.get("name") in ("web_search", "web_fetch"):
                            tool_name = cb["name"]
                            current_tool_block_index = evt.get("index")
                            tool_input_parts = []
                    elif etype == "content_block_delta":
                        delta = evt.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text_parts.append(delta.get("text", ""))
                        elif (
                            delta.get("type") == "input_json_delta"
                            and evt.get("index") == current_tool_block_index
                        ):
                            tool_input_parts.append(delta.get("partial_json", ""))
                except (json.JSONDecodeError, KeyError, AttributeError):
                    pass

        tool_input: dict[str, Any] | None = None
        if tool_name and tool_input_parts:
            try:
                tool_input = json.loads("".join(tool_input_parts))
            except json.JSONDecodeError:
                tool_name = None  # malformed tool call — treat as normal response

        return chunks, text_parts, tool_name, tool_input

    async def _stream_and_save() -> AsyncIterator[str]:
        text_parts: list[str] = []
        try:
            cur_request = MessagesRequest(
                model=body.model,
                messages=loop_messages,  # type: ignore[arg-type]
                max_tokens=body.max_tokens,
                stream=True,
                tools=injected_tools,  # type: ignore[arg-type]
            )
            resp = service.create_message(cur_request)
            first_iter: AsyncIterator[str] = resp.body_iterator  # type: ignore[union-attr]

            if not injected_tools:
                # No tools injected — stream directly without buffering.
                async for chunk in first_iter:
                    yield chunk
                    for line in chunk.splitlines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:].strip())
                            if evt.get("type") == "content_block_delta":
                                d = evt.get("delta", {})
                                if d.get("type") == "text_delta":
                                    text_parts.append(d.get("text", ""))
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            pass
            else:
                chunks, first_text, tool_name, tool_input = await _collect_response(first_iter)

                if tool_name and tool_input and settings.tavily_api_key:
                    # Model wants to use a web tool — execute via Tavily silently.
                    logger.info("UI agentic tool: {}", tool_name)
                    try:
                        if tool_name == "web_search":
                            query = str(tool_input.get("query", ""))
                            results = await _tavily_search(settings.tavily_api_key, query)
                            tool_result_content = (
                                "\n\n".join(
                                    f"{r['title']}\n{r['url']}\n{r.get('snippet', '')}"
                                    for r in results
                                )
                                or "No results found."
                            )
                        else:
                            url = str(tool_input.get("url", ""))
                            fetched = await _tavily_fetch(settings.tavily_api_key, url)
                            tool_result_content = fetched["data"]
                    except Exception as tool_err:
                        logger.warning("UI agentic tool error: {}", tool_err)
                        tool_result_content = f"Web tool failed: {type(tool_err).__name__}"

                    # Append assistant tool_use + tool_result for follow-up.
                    loop_messages.append({
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "srvtoolu_ui", "name": tool_name, "input": tool_input}],
                    })
                    loop_messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "srvtoolu_ui", "content": tool_result_content}],
                    })

                    # Second call — stream the final answer directly.
                    follow_req = MessagesRequest(
                        model=body.model,
                        messages=loop_messages,  # type: ignore[arg-type]
                        max_tokens=body.max_tokens,
                        stream=True,
                        tools=injected_tools,  # type: ignore[arg-type]
                    )
                    follow_resp = service.create_message(follow_req)
                    follow_iter: AsyncIterator[str] = follow_resp.body_iterator  # type: ignore[union-attr]

                    async for chunk in follow_iter:
                        yield chunk
                        for line in chunk.splitlines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                evt = json.loads(line[5:].strip())
                                if evt.get("type") == "content_block_delta":
                                    d = evt.get("delta", {})
                                    if d.get("type") == "text_delta":
                                        text_parts.append(d.get("text", ""))
                            except (json.JSONDecodeError, KeyError, AttributeError):
                                pass
                else:
                    # Normal response (no tool call) — yield buffered chunks.
                    for chunk in chunks:
                        yield chunk
                    text_parts = list(first_text)

        except Exception as e:
            logger.warning("UI chat stream error: {}", type(e).__name__)
            if not text_parts:
                yield '{"type":"error","error":{"type":"api_error","message":"Stream interrupted – please retry"}}\n\n'
        finally:
            full_text = "".join(text_parts)
            if full_text:
                try:
                    await db.add_message(session_id, "assistant", full_text)
                except Exception as save_err:
                    logger.warning(
                        "UI: failed to persist assistant message: {}",
                        type(save_err).__name__,
                    )

    return StreamingResponse(
        _stream_and_save(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
