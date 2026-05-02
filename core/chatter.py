"""Strip verbose chatter prefixes from local / open-weight model responses.

Only operates on the very beginning of the first text block — once meaningful
content has been emitted the filter becomes a no-op for the rest of the stream.
"""

from __future__ import annotations

import re

# A sentence boundary: period/exclamation/question followed by whitespace
# and a capital letter or a known content-start word.
_SENTENCE_SPLIT = re.compile(r"[.!?]\s+")

# Words/phrases that signal actual content is starting, not more filler.
# Excludes ambiguous starters like "let " or "here" that also begin filler.
_CONTENT_STARTERS = frozenset({
    "first", "next", "then", "now", "to", "for", "if", "when",
    "after", "before", "with", "using", "by", "start", "create",
    "use", "run", "check", "see", "try", "add", "open", "write",
    "build", "install", "update", "delete", "remove", "change",
    "modify", "set", "copy", "move", "rename", "replace",
    "def ", "class ", "import ", "from ", "return ", "async ", "await ",
    "const ", "var ", "function ", "#!", "//", "/*", "```",
    "step", "note", "important", "warning", "caution",
    "the", "this", "that", "these", "those",
})

# Known chatter opening keywords (case-insensitive prefix match).
_CHATTER_KEYWORDS = (
    "certainly",
    "of course",
    "sure",
    "absolutely",
    "great",
    "good",
    "alright",
    "ok",
    "okay",
    "i'd be",
    "i would be",
    "i'll be",
    "i will be",
    "i'm happy",
    "i am happy",
    "i'm glad",
    "i am glad",
    "i'd like to",
    "i would like to",
    "i can help",
    "i could help",
    "i'll help",
    "i will help",
    "let me",
    "allow me to",
    "here's what",
    "here is what",
)

_CHATTER_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(s) for s in _CHATTER_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Secondary-chatter: sentences that continue the filler after the opening keyword.
_SECONDARY_CHATTER = re.compile(
    r"^(?:I\s*(?:'ll|will|can|could|'d|would|'m|am)\s+)?"
    r"(?:be\s+)?(?:happy|glad|willing|pleased)\s+to\s+"
    r"(?:help|assist|do that|handle that|explain|clarify|walk you through|break (?:that|it) down)"
    r"\b",
    re.IGNORECASE,
)

# Simple help-offer pattern: "I can help with that.", "Let me assist you with this."
_SIMPLE_HELP_RE = re.compile(
    r"^(?:I\s*(?:can|could|'ll|will|'d|would)\s+|Let me\s+|Allow me to\s+)"
    r"(?:help|assist)\b.*\b(?:that|this|you)\b[.!?]?\s*$",
    re.IGNORECASE,
)

_BUFFER_CAP = 300


class ChatterStripper:
    """Stateful per-stream filter that strips opening chatter from the first text block."""

    def __init__(self) -> None:
        self._buffer = ""
        self._stripped = False

    def feed(self, text: str) -> str:
        """Return *text* with opening chatter removed, or *text* unchanged after first block."""
        if self._stripped:
            return text

        self._buffer += text

        if len(self._buffer) >= _BUFFER_CAP:
            self._stripped = True
            result = self._buffer
            self._buffer = ""
            return result

        return ""

    def flush(self) -> str:
        """Return any buffered text that hasn't been emitted yet."""
        if self._stripped:
            return ""
        self._stripped = True
        text = self._buffer
        self._buffer = ""
        return _strip_opening_chatter(text)


def _strip_opening_chatter(text: str) -> str:
    """Strip opening chatter sentences from the beginning of *text*.

    Splits the text into sentences and removes leading sentences that are
    filler, stopping at the first sentence that looks like actual content.
    """
    if not text.strip():
        return text

    # Quick check: does it even start with a chatter keyword?
    if not _CHATTER_PREFIX_RE.match(text):
        return text

    # Split into sentences while keeping the delimiters.
    parts = _SENTENCE_SPLIT.split(text, maxsplit=10)
    if len(parts) <= 1:
        # Single sentence — strip the whole thing if it's pure filler,
        # or keep it if it has substantial content.
        if _is_filler_sentence(text):
            _log_chatter_stripped(text, "")
            return ""
        return text

    # Walk sentences, stripping filler from the front.
    cut = 0
    sentences = _split_sentences(text)
    for i, sentence in enumerate(sentences):
        stripped = sentence.strip()
        if not stripped:
            cut = _sentence_end(text, i, sentences)
            continue
        if _is_filler_sentence(stripped):
            # If the filler sentence has a colon with content after it,
            # only strip the filler prefix before the colon.
            after_colon = _split_at_colon(stripped)
            if after_colon is not None:
                # Return from the colon boundary within this sentence.
                offset = _sentence_start(text, i, sentences)
                colon_pos = text.find(":", offset + cut) + 1
                # Skip whitespace after colon.
                while colon_pos < len(text) and text[colon_pos] == " ":
                    colon_pos += 1
                return text[colon_pos:]
            cut = _sentence_end(text, i, sentences)
            continue
        break

    if cut >= len(text):
        _log_chatter_stripped(text, "")
        return ""
    result = text[cut:]
    _log_chatter_stripped(text, result)
    return result


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping trailing punctuation."""
    result: list[str] = []
    start = 0
    for m in _SENTENCE_SPLIT.finditer(text):
        end = m.end()
        result.append(text[start:end])
        start = end
    if start < len(text):
        result.append(text[start:])
    return result


def _sentence_end(text: str, idx: int, sentences: list[str]) -> int:
    """Return the character offset just after sentence *idx*."""
    offset = 0
    for i in range(idx + 1):
        if i < len(sentences):
            offset += len(sentences[i])
    return offset


def _sentence_start(text: str, idx: int, sentences: list[str]) -> int:
    """Return the character offset where sentence *idx* begins."""
    offset = 0
    for i in range(idx):
        if i < len(sentences):
            offset += len(sentences[i])
    return offset


def _split_at_colon(sentence: str) -> str | None:
    """If *sentence* is filler with a colon, return the content after the colon.

    Returns None if there's no colon or the part after the colon is not
    meaningful content.
    """
    if ":" not in sentence:
        return None
    idx = sentence.index(":")
    after = sentence[idx + 1:].strip()
    if not after:
        return None
    # The part after the colon should look like actual content.
    after_lower = after.lower()
    if any(after_lower.startswith(w) for w in _CONTENT_STARTERS):
        return after
    # Short fragments after colon — probably content too.
    if len(after.split()) <= 5 and any(c.isalpha() for c in after):
        return after
    return None


def _is_filler_sentence(sentence: str) -> bool:
    """True if *sentence* is a filler/chatter sentence with no real content."""
    s = sentence.strip().lower()
    # Very short sentences are likely filler.
    if len(s) < 5:
        return True
    # Sentence contains code or technical markers — not filler.
    if _has_technical_content(s):
        return False
    # Contains help/assist/explain keywords.
    has_filler_word = any(
        w in s for w in (
            "help", "assist", "happy", "glad", "sure", "course",
            "certainly", "absolutely", "question", "explain",
            "walk you", "break it", "break that",
            "i'll do", "i will do", "i can do", "my plan",
        )
    )
    if has_filler_word:
        return True
    # Secondary filler like "I can help you with that."
    if _SECONDARY_CHATTER.match(s):
        return True
    if _SIMPLE_HELP_RE.match(s):
        return True
    # Starts with a chatter keyword (from the prefix match) and is short.
    if _CHATTER_PREFIX_RE.match(s) and len(s) < 80:
        return True
    return False


def _has_technical_content(sentence: str) -> bool:
    """True if *sentence* contains code, file paths, or other technical markers."""
    # Code indicators.
    for marker in ("```", "def ", "class ", "import ", "function ", "=>", "()", "->",
                   ".py", ".js", ".ts", ".json", ".yaml", ".toml", ".md",
                   "npm ", "pip ", "git ", "curl ", "docker ", "sudo "):
        if marker in sentence:
            return True
    # Starts with a content word (actual task beginning).
    for w in _CONTENT_STARTERS:
        if sentence.startswith(w):
            return True
    return False


# Rate-limited logging to prevent spam on verbose models
_chatter_log_count = 0
_chatter_log_suppressed = 0


def _log_chatter_stripped(original: str, remaining: str) -> None:
    """Log when chatter is stripped from a response (rate-limited)."""
    from loguru import logger

    global _chatter_log_count, _chatter_log_suppressed

    stripped_len = len(original) - len(remaining)
    if stripped_len <= 0:
        return

    _chatter_log_count += 1
    # Log first 5 strips per session, then 1 in 10, rest suppressed
    if _chatter_log_count <= 5 or _chatter_log_count % 10 == 0:
        preview = original[:80].replace("\n", " ")
        if remaining:
            logger.info(
                "CHATTER_STRIP #{}: removed {} chars from '{}...' → '{}...'",
                _chatter_log_count,
                stripped_len,
                preview,
                remaining[:40].replace("\n", " "),
            )
        else:
            logger.info(
                "CHATTER_STRIP #{}: removed entire opening ({} chars): '{}...'",
                _chatter_log_count,
                stripped_len,
                preview,
            )
    else:
        _chatter_log_suppressed += 1
        if _chatter_log_suppressed % 20 == 0:
            logger.debug(
                "CHATTER_STRIP: {} strips suppressed since last log",
                _chatter_log_suppressed,
            )


def _is_secondary_filler(sentence: str) -> bool:
    """True if *sentence* is a continuation filler after the opening keyword."""
    s = sentence.strip().lower()
    return _SECONDARY_CHATTER.match(s) is not None