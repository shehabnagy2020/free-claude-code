"""Background session summary generation using the proxy's LLM infrastructure."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from config.settings import Settings, get_settings

from .models.anthropic import MessagesRequest, Message
from .services import ClaudeProxyService
from .ui_db import UIChatDB
from .dependencies import resolve_provider

SUMMARY_SYSTEM_PROMPT = """\
You are a conversation summarizer. Produce a concise running summary of a chat conversation.

Capture:
1. Main topics discussed
2. Any decisions, conclusions, or outcomes
3. Things the user explicitly asked to remember — always prefix with "REMEMBER:"
4. Current state of any ongoing work or tasks

Rules:
- Keep the summary under 200 words
- Write in clear concise prose, not bullet points
- Preserve any existing "REMEMBER:" items verbatim
- If the user says "remember this", "note this", "keep this in mind", \
"don't forget", "save this", or "write this down", add it as a "REMEMBER:" item
- Focus on information that would help someone resume the conversation later
- No pleasantries or meta-commentary, only substantive content"""


_GLOBAL_MEMORY_HEADER = "## Persistent Memory"


def _strip_global_memory_section(text: str | None) -> str | None:
    """Remove a previously injected global memory section from a summary."""
    if not text:
        return text
    idx = text.find(_GLOBAL_MEMORY_HEADER)
    if idx < 0:
        return text
    return text[:idx].rstrip()


async def generate_summary(
    db: UIChatDB,
    session_id: str,
    settings: Settings,
    provider_getter: Any,
    model: str | None = None,
) -> str | None:
    """Generate or update a session summary via the LLM.

    Uses an incremental approach: sends the existing summary (if any) plus
    the last few messages, keeping token usage bounded.

    Returns the new summary text, or None if summarization is skipped/fails.
    """
    # Resolve model: use caller's model if provided, else fall back to configured default.
    if not model:
        model = settings.model

    existing_summary = await db.get_summary(session_id)
    # Strip previous global memory section before sending to the LLM
    # so it doesn't compound across summary updates.
    llm_existing = _strip_global_memory_section(existing_summary)
    recent = await db.get_recent_messages(session_id, limit=6)

    # Don't summarize if there are no assistant messages yet
    if not any(m["role"] == "assistant" for m in recent):
        return existing_summary

    # Truncate long messages for the summarizer
    formatted: list[str] = []
    for msg in recent:
        label = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        # Strip image blocks from JSON content
        if content.startswith("["):
            try:
                blocks = json.loads(content)
                texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                content = " ".join(texts) if texts else "[image]"
            except (json.JSONDecodeError, TypeError):
                pass
        if len(content) > 500:
            content = content[:500] + "…"
        formatted.append(f"{label}: {content}")

    messages_text = "\n\n".join(formatted)

    if llm_existing:
        user_content = (
            f"Current summary:\n{llm_existing}\n\n"
            f"The conversation has continued. Update the summary based on the recent messages below.\n\n"
            f"Recent messages:\n{messages_text}\n\n"
            f"Produce an updated summary."
        )
    else:
        user_content = (
            f"This is a new conversation. Write an initial summary based on the messages below.\n\n"
            f"Messages:\n{messages_text}\n\n"
            f"Produce a summary."
        )

    service = ClaudeProxyService(
        settings,
        provider_getter=provider_getter,
    )

    summary_request = MessagesRequest(
        model=model,
        messages=[Message(role="user", content=user_content)],
        system=SUMMARY_SYSTEM_PROMPT,
        max_tokens=1024,
        stream=True,
    )

    try:
        resp = service.create_message(summary_request)
        stream_iter: AsyncIterator[str] = resp.body_iterator  # type: ignore[union-attr]
        text_parts: list[str] = []
        async for chunk in stream_iter:
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

        summary_text = "".join(text_parts).strip()
        if summary_text:
            await _extract_remember_items(db, summary_text)
            # Prepend current global memory so it stays in the session summary
            _memory_text = await db.get_global_memory_text()
            if _memory_text:
                summary_text = f"{_memory_text}\n\n{summary_text}"
            await db.update_summary(session_id, summary_text)
            return summary_text
    except Exception as exc:
        logger.warning(
            "UI: summary generation failed: {} {}", type(exc).__name__, exc
        )

    return existing_summary


async def _extract_remember_items(db: UIChatDB, summary_text: str) -> None:
    """Parse memory items from a summary and upsert them into global memory.

    Detects keywords: REMEMBER:, KEEP:, NOTE:, DON'T FORGET:, SAVE:
    """
    import re
    _MEMORY_TAG = re.compile(
        r"(?:REMEMBER|KEEP|NOTE|DON'?T\s+FORGET|SAVE)\s*:\s*(.+?)(?=(?:\.?\s*(?:REMEMBER|KEEP|NOTE|DON'?T\s+FORGET|SAVE)\s*:)|\.?$)",
        re.IGNORECASE,
    )
    for match in _MEMORY_TAG.finditer(summary_text):
        item = match.group(1).strip().rstrip(".,;:")
        if not item:
            continue
        key = item[:50].rstrip(".,;:")
        await db.upsert_global_memory(key, item)