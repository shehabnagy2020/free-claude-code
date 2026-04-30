"""Web UI API routes – auth, sessions, messages, streaming chat proxy."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from config.settings import get_settings

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
    Stream a response from the provider via the local /v1/messages endpoint.
    Saves user + assistant messages to the DB around the stream.
    """
    if not await db.session_exists(body.session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Build Anthropic content blocks for this user turn.
    # If images are attached, content is a list of blocks; otherwise plain text.
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
        # Persist as JSON so the frontend can render image thumbnails from history
        user_content_for_db = json.dumps(user_blocks)
    else:
        user_content_for_api = body.content
        user_content_for_db = body.content

    # Save user message to DB
    await db.add_message(body.session_id, "user", user_content_for_db)

    # Build full history for the API request.
    # Messages stored as JSON arrays are passed as structured content blocks;
    # plain strings are passed as-is.
    def _parse_content(raw: str) -> list[dict[str, Any]] | str:
        if raw.startswith("["):
            try:
                return json.loads(raw)  # type: ignore[return-value]
            except json.JSONDecodeError:
                pass
        return raw

    history = await db.get_messages(body.session_id)
    messages = [{"role": m["role"], "content": _parse_content(m["content"])} for m in history]

    settings = get_settings()
    port = settings.port
    api_url = f"http://127.0.0.1:{port}/v1/messages"

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if settings.anthropic_auth_token:
        headers["x-api-key"] = settings.anthropic_auth_token

    payload: dict[str, Any] = {
        "model": body.model,
        "messages": messages,
        "stream": True,
        "max_tokens": body.max_tokens,
    }

    session_id = body.session_id
    user_text_for_title = body.content.strip() or "🖼️ Image"

    async def _stream_and_save() -> AsyncIterator[str]:
        text_parts: list[str] = []
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0),
                limits=httpx.Limits(keepalive_expiry=30.0),
            ) as client:
                async with client.stream(
                    "POST", api_url, json=payload, headers=headers
                ) as resp:
                    async for raw_line in resp.aiter_lines():
                        # Re-emit the line with newline restored
                        yield (raw_line + "\n") if raw_line else "\n"

                        # Buffer text deltas for DB persistence
                        if raw_line.startswith("data:"):
                            data_str = raw_line[5:].strip()
                            try:
                                evt = json.loads(data_str)
                                if evt.get("type") == "content_block_delta":
                                    delta = evt.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        text_parts.append(delta.get("text", ""))
                            except (json.JSONDecodeError, KeyError, AttributeError):
                                pass

        except Exception as e:
            logger.warning("UI chat stream error: {}", type(e).__name__)
            yield "data: {\"type\":\"error\",\"error\":{\"type\":\"api_error\",\"message\":\"Connection lost\"}}\n\n"
        finally:
            full_text = "".join(text_parts)
            if full_text:
                try:
                    await db.add_message(session_id, "assistant", full_text)
                    # Auto-title: set title from first user message if still 'New Chat'
                    sessions = await db.list_sessions()
                    for s in sessions:
                        if s["id"] == session_id and s["title"] == "New Chat":
                            new_title = user_text_for_title[:60].replace("\n", " ")
                            if len(user_text_for_title) > 60:
                                new_title += "…"
                            await db.update_session(session_id, title=new_title)
                            break
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
