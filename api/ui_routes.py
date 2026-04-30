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

    service = ClaudeProxyService(
        settings,
        provider_getter=lambda pt: resolve_provider(pt, app=request.app, settings=settings),
    )

    session_id = body.session_id
    loop_messages: list[dict[str, Any]] = list(api_messages)

    # --- Proactive Tavily search ------------------------------------------------
    # Detect real-time queries and inject Tavily results into the system prompt
    # before the LLM call. No tool round-trip — works with any model.
    _REALTIME_KEYWORDS = (
        "weather", "news", "price", "score", "stock", "today", "current",
        "latest", "now", "forecast", "temperature", "breaking", "live",
        "match", "result", "rate", "trending", "happened", "update", "search", "find", "look up"
    )
    _user_text_lower = body.content.lower()
    _needs_search = (
        settings.tavily_api_key
        and any(kw in _user_text_lower for kw in _REALTIME_KEYWORDS)
    )
    _tavily_system: str | None = None
    if _needs_search:
        try:
            _results = await _tavily_search(settings.tavily_api_key, body.content)
            if _results:
                _snippets = "\n\n".join(
                    f"{r['title']}\n{r['url']}\n{r.get('snippet', '')}"
                    for r in _results
                )
                _tavily_system = (
                    "The following are live web search results for the user's query. "
                    f"Use them to answer accurately with up-to-date information:\n\n{_snippets}"
                )
                logger.info("UI proactive search: {} results for {!r}", len(_results), body.content[:80])
        except Exception as _search_err:
            logger.warning("UI proactive search failed: {}", _search_err)
    # ---------------------------------------------------------------------------

    async def _stream_and_save() -> AsyncIterator[str]:
        text_parts: list[str] = []
        try:
            cur_request = MessagesRequest(
                model=body.model,
                messages=loop_messages,  # type: ignore[arg-type]
                max_tokens=body.max_tokens,
                stream=True,
                system=_tavily_system,
            )
            resp = service.create_message(cur_request)
            stream_iter: AsyncIterator[str] = resp.body_iterator  # type: ignore[union-attr]
            async for chunk in stream_iter:
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
