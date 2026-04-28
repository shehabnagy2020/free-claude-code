"""Platform-agnostic message models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ImageAttachment:
    """Image attachment with base64 data and media type."""

    data: str  # base64-encoded image data
    media_type: str  # e.g. "image/png", "image/jpeg"
    filename: str | None = None


@dataclass
class IncomingMessage:
    """
    Platform-agnostic incoming message.

    Adapters convert platform-specific events to this format.
    """

    text: str
    chat_id: str
    user_id: str
    message_id: str
    platform: str  # "telegram", "discord", "slack", etc.

    # Optional fields
    reply_to_message_id: str | None = None
    # Forum topic ID (Telegram); required when replying in forum supergroups
    message_thread_id: str | None = None
    username: str | None = None
    # Pre-sent status message ID (e.g. "Transcribing voice note..."); handler edits in place
    status_message_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Image attachments (platform-agnostic)
    images: list[ImageAttachment] = field(default_factory=list)

    # Platform-specific raw event for edge cases
    raw_event: Any = None

    def is_reply(self) -> bool:
        """Check if this message is a reply to another message."""
        return self.reply_to_message_id is not None

    def has_images(self) -> bool:
        """Check if this message has image attachments."""
        return bool(self.images)
