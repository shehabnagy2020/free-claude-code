"""Unit tests for ChatterStripper in core/chatter.py."""

import pytest
from core.chatter import ChatterStripper, _strip_opening_chatter, _is_filler_sentence


class TestChatterStripper:
    """Tests for the ChatterStripper class."""

    def test_strips_certainly_prefix(self):
        """Test stripping 'Certainly!' prefix."""
        stripper = ChatterStripper()
        result = stripper.feed("Certainly! I can help with that. ")
        # Buffering until flush
        assert result == ""
        flushed = stripper.flush()
        assert "Certainly" not in flushed
        assert "help with that" in flushed

    def test_strips_of_course_prefix(self):
        """Test stripping 'Of course!' prefix."""
        stripper = ChatterStripper()
        stripper.feed("Of course! ")
        stripper.feed("Here's the solution: ")
        result = stripper.flush()
        assert "Of course" not in result
        assert "solution" in result

    def test_strips_let_me_prefix(self):
        """Test stripping 'Let me' prefix."""
        stripper = ChatterStripper()
        stripper.feed("Let me help you with that. ")
        result = stripper.flush()
        assert "Let me" not in result

    def test_strips_i_can_help_prefix(self):
        """Test stripping 'I can help' prefix."""
        stripper = ChatterStripper()
        stripper.feed("I can help with that. ")
        result = stripper.flush()
        assert "I can help" not in result

    def test_no_stripping_for_content_start(self):
        """Test that content starting with technical terms is not stripped."""
        stripper = ChatterStripper()
        stripper.feed("def main():\n    pass")
        result = stripper.flush()
        assert "def main" in result

    def test_no_stripping_after_first_block(self):
        """Test that stripper passes through text after first block."""
        stripper = ChatterStripper()
        stripper.feed("Certainly! ")
        stripper.flush()  # First block done
        result = stripper.feed("Second block content")
        assert result == "Second block content"

    def test_buffer_cap_triggers_flush(self):
        """Test that buffer cap triggers automatic flush."""
        stripper = ChatterStripper()
        long_text = "A" * 350  # Exceeds _BUFFER_CAP of 300
        result = stripper.feed(long_text)
        assert result == long_text  # Returned as-is after cap
        assert stripper._stripped is True

    def test_empty_input(self):
        """Test handling empty input."""
        stripper = ChatterStripper()
        result = stripper.feed("")
        assert result == ""
        flushed = stripper.flush()
        assert flushed == ""

    def test_colon_aware_splitting(self):
        """Test that content after colon is preserved."""
        result = _strip_opening_chatter("Certainly! Here's the answer: do this")
        assert "answer: do this" in result or "do this" in result


class TestIsFillerSentence:
    """Tests for _is_filler_sentence helper."""

    def test_detects_certainly(self):
        assert _is_filler_sentence("Certainly! I can help.") is True

    def test_detects_of_course(self):
        assert _is_filler_sentence("Of course, let me assist.") is True

    def test_detects_happy_to_help(self):
        assert _is_filler_sentence("I'm happy to help with that.") is True

    def test_allows_code(self):
        assert _is_filler_sentence("def foo(): pass") is False

    def test_allows_file_paths(self):
        assert _is_filler_sentence("Check the file at /etc/config.py") is False

    def test_allows_commands(self):
        assert _is_filler_sentence("Run `npm install` to proceed.") is False

    def test_short_sentence_is_filler(self):
        assert _is_filler_sentence("Sure.") is True

    def test_long_content_sentence_not_filler(self):
        sentence = "The first step is to initialize the configuration file."
        assert _is_filler_sentence(sentence) is False
