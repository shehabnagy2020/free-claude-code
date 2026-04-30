"""Web UI API routes – auth, sessions, messages, streaming chat proxy."""

from __future__ import annotations

import json
import secrets
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

# In-memory set of valid session tokens (cleared on server restart → re-login).
_active_tokens: set[str] = set()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_db(request: Request) -> UIChatDB:
    return request.app.state.ui_db  # type: ignore[attr-defined]


def _verify_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token or token not in _active_tokens:
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
    token = secrets.token_hex(32)
    _active_tokens.add(token)
    return {"token": token, "ok": True}


@ui_router.post("/auth/logout")
async def logout(request: Request) -> dict[str, bool]:
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    _active_tokens.discard(token)
    return {"ok": True}


# ── Config ────────────────────────────────────────────────────────────────────


# Claude model id → friendly display name shown in the UI
_CLAUDE_DISPLAY_NAMES: dict[str, str] = {
    "claude-opus-4": "Claude Opus 4",
    "claude-3-7-sonnet": "Claude 3.7 Sonnet",
    "claude-3-5-sonnet": "Claude 3.5 Sonnet",
    "claude-3-5-haiku": "Claude 3.5 Haiku",
    "claude-3-opus": "Claude 3 Opus",
    "claude-3-sonnet": "Claude 3 Sonnet",
    "claude-3-haiku": "Claude 3 Haiku",
}


def _claude_display_name(claude_model_id: str) -> str:
    """Return a human-readable Claude model name for the given model ID."""
    lower = claude_model_id.lower()
    # Match longest prefix first so 'claude-3-5-sonnet' beats 'claude-3-sonnet'
    for key in sorted(_CLAUDE_DISPLAY_NAMES, key=len, reverse=True):
        if key in lower:
            return _CLAUDE_DISPLAY_NAMES[key]
    # Fallback: strip date suffix and title-case
    base = lower.rsplit("-", 1)[0] if lower[-8:].isdigit() else lower
    return base.replace("-", " ").title()


def _provider_display(model_str: str) -> str:
    """Convert 'provider_type/model/name' → human-readable provider label."""
    parts = model_str.split("/", 1)
    provider_id = parts[0]
    model_name = parts[1] if len(parts) > 1 else ""
    provider_label = provider_id.replace("_", " ").title()
    return f"{provider_label} › {model_name}" if model_name else provider_label


@ui_router.get("/config")
async def get_config(_: Token) -> dict[str, Any]:
    """Return available model routes derived from current settings."""
    settings = get_settings()
    models: list[dict[str, Any]] = []

    # Default model (settings.model) maps to Opus 4 by convention
    if settings.model:
        default_claude_id = "claude-opus-4-20250514"
        models.append(
            {
                "label": _claude_display_name(default_claude_id),
                "target": settings.model,
                "claude_model": default_claude_id,
                "provider_display": _provider_display(settings.model),
                "is_default": True,
            }
        )

    # Per-tier overrides (MODEL_OPUS / MODEL_SONNET / MODEL_HAIKU)
    named: list[tuple[str | None, str]] = [
        (settings.model_opus, "claude-3-opus-20240229"),
        (settings.model_sonnet, "claude-3-5-sonnet-20241022"),
        (settings.model_haiku, "claude-3-haiku-20240307"),
    ]
    for override, claude_id in named:
        if override:
            models.append(
                {
                    "label": _claude_display_name(claude_id),
                    "target": override,
                    "claude_model": claude_id,
                    "provider_display": _provider_display(override),
                    "is_default": False,
                }
            )

    if not models:
        fallback_id = "claude-opus-4-20250514"
        models.append(
            {
                "label": _claude_display_name(fallback_id),
                "target": "",
                "claude_model": fallback_id,
                "provider_display": "",
                "is_default": True,
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

    # Save user message first
    await db.add_message(body.session_id, "user", body.content)

    # Build full history for context
    history = await db.get_messages(body.session_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

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
    user_content = body.content

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
                            new_title = user_content[:60].replace("\n", " ")
                            if len(user_content) > 60:
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
