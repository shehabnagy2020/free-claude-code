"""SQLite persistence for the web UI – sessions and messages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

_DB_PATH = "ui_chat.db"

_CREATE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'New Chat',
    model       TEXT NOT NULL DEFAULT 'claude-opus-4-20250514',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_to_dict(row: aiosqlite.Row, message_count: int = 0) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": message_count,
        "summary": row["summary"],
    }


def _message_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


class UIChatDB:
    """Async SQLite database for UI chat sessions and messages."""

    def __init__(self, db_path: str = _DB_PATH) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        """Create tables if they don't exist (called once at startup)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(_CREATE_SCHEMA)
            # Migration: add summary column if missing
            async with db.execute("PRAGMA table_info(sessions)") as cursor:
                columns = await cursor.fetchall()
            if not any(col[1] == "summary" for col in columns):
                await db.execute(
                    "ALTER TABLE sessions ADD COLUMN summary TEXT DEFAULT NULL"
                )
            # Create global_memory table
            await db.execute(
                "CREATE TABLE IF NOT EXISTS global_memory ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            await db.commit()

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT s.*, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [_session_to_dict(row, row["message_count"]) for row in rows]

    async def create_session(self, title: str, model: str) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = _now()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, model, now, now),
            )
            await db.commit()
        return {
            "id": session_id,
            "title": title,
            "model": model,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "summary": None,
        }

    async def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        model: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any] | None:
        parts: list[str] = []
        values: list[Any] = []
        if title is not None:
            parts.append("title = ?")
            values.append(title)
        if model is not None:
            parts.append("model = ?")
            values.append(model)
        if summary is not None:
            parts.append("summary = ?")
            values.append(summary)
        now = _now()
        parts.append("updated_at = ?")
        values.append(now)
        values.append(session_id)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                f"UPDATE sessions SET {', '.join(parts)} WHERE id = ?",  # noqa: S608
                values,
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _session_to_dict(row)

    async def delete_session(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            await db.commit()
        return (cursor.rowcount or 0) > 0

    async def session_exists(self, session_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                return (await cursor.fetchone()) is not None

    async def get_history_for_chat(
        self, session_id: str
    ) -> list[dict[str, Any]] | None:
        """Return message history in one query, or None if session doesn't exist."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Single query: LEFT JOIN so we get a row even when messages are empty.
            # The sessions row lets us distinguish missing-session vs empty-session.
            async with db.execute(
                """
                SELECT s.id AS _sid, m.id, m.session_id, m.role, m.content, m.created_at
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.id = ?
                ORDER BY m.created_at ASC
                """,
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        if not rows:
            return None  # session doesn't exist
        # LEFT JOIN may produce a single row with m.id = NULL (empty session)
        return [_message_to_dict(row) for row in rows if row["id"] is not None]

    async def get_session_title(self, session_id: str) -> str | None:
        """Return the session title, or None if not found."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    # ── Messages ──────────────────────────────────────────────────────────────

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_message_to_dict(row) for row in rows]

    async def add_message(
        self, session_id: str, role: str, content: str
    ) -> dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = _now()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, now),
            )
            await db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            await db.commit()
        return {
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": now,
        }

    # ── Summary ────────────────────────────────────────────────────────────────

    async def get_summary(self, session_id: str) -> str | None:
        """Return the session summary, or None if not found."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT summary FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None

    async def update_summary(self, session_id: str, summary: str) -> None:
        """Write the session summary and bump updated_at."""
        now = _now()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, session_id),
            )
            await db.commit()

    async def get_recent_messages(
        self, session_id: str, limit: int = 6
    ) -> list[dict[str, Any]]:
        """Fetch the last N messages (chronological order) with truncated content."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT role, content FROM messages WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        # Return in chronological order (oldest first)
        return [
            {
                "role": row["role"],
                "content": row["content"][:500]
                if len(row["content"]) > 500
                else row["content"],
            }
            for row in reversed(rows)
        ]

    # ── Global Memory ────────────────────────────────────────────────────────

    async def get_all_global_memory(self) -> list[dict[str, Any]]:
        """Return all global memory entries ordered by key."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT key, value, updated_at FROM global_memory ORDER BY key"
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {"key": row["key"], "value": row["value"], "updated_at": row["updated_at"]}
            for row in rows
        ]

    async def get_global_memory_text(self) -> str | None:
        """Return all global memory entries as a formatted block, or None if empty."""
        entries = await self.get_all_global_memory()
        if not entries:
            return None
        lines = [f"- {e['value']}" for e in entries]
        return "## Persistent Memory\n" + "\n".join(lines)

    async def upsert_global_memory(self, key: str, value: str) -> None:
        """Insert or update a global memory entry.

        Ensures uniqueness by:
        1. Key collision: updates existing entry if key already exists
        2. Value collision: if same normalized value exists, removes old entry
        """
        now = _now()
        normalized = self._normalize_memory_value(value)
        async with aiosqlite.connect(self._db_path) as db:
            # Check if a normalized version of this value already exists
            async with db.execute("SELECT key, value FROM global_memory") as cursor:
                all_entries = await cursor.fetchall()

            for entry in all_entries:
                if self._normalize_memory_value(entry[1]) == normalized:
                    # Duplicate found - remove old entry
                    await db.execute(
                        "DELETE FROM global_memory WHERE key = ?", (entry[0],)
                    )
                    break

            # Insert/update with the new key
            await db.execute(
                "INSERT INTO global_memory (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?",
                (key, value, now, value, now),
            )
            await db.commit()

    @staticmethod
    def _normalize_memory_value(value: str) -> str:
        """Normalize a value for duplicate detection.

        - Lowercase
        - Collapse whitespace
        - Strip leading/trailing whitespace
        - Remove trailing punctuation
        """
        import re

        normalized = value.lower().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.rstrip(".,;:!?")
        return normalized

    async def delete_global_memory(self, key: str) -> bool:
        """Delete a global memory entry. Returns True if deleted."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM global_memory WHERE key = ?", (key,))
            await db.commit()
        return (cursor.rowcount or 0) > 0
