"""Unit tests for context-mode nudge in core/nudge.py."""

import pytest
from core.nudge import CONTEXT_MODE_NUDGE, CONTEXT_MODE_NUDGE_SHORT


class TestContextModeNudge:
    """Tests for context-mode nudge content."""

    def test_nudge_has_mandatory_header(self):
        """Test that full nudge has CONTEXT-MODE SANDBOX header."""
        assert "CONTEXT-MODE SANDBOX" in CONTEXT_MODE_NUDGE
        assert "MANDATORY" in CONTEXT_MODE_NUDGE

    def test_nudge_mentions_ctx_execute(self):
        """Test that nudge mentions ctx_execute function."""
        assert "ctx_execute" in CONTEXT_MODE_NUDGE

    def test_nudge_mentions_ctx_execute_file(self):
        """Test that nudge mentions ctx_execute_file function."""
        assert "ctx_execute_file" in CONTEXT_MODE_NUDGE

    def test_nudge_blocks_curl_wget(self):
        """Test that nudge explicitly blocks curl/wget."""
        assert "curl" in CONTEXT_MODE_NUDGE.lower()
        assert "wget" in CONTEXT_MODE_NUDGE.lower()

    def test_nudge_allows_proxy_web_tools(self):
        """Test that nudge clarifies proxy web_search/web_fetch are fine."""
        assert "web_search" in CONTEXT_MODE_NUDGE
        assert "web_fetch" in CONTEXT_MODE_NUDGE
        assert "Tavily" in CONTEXT_MODE_NUDGE

    def test_nudge_has_tool_routing_section(self):
        """Test that nudge has tool routing guidance."""
        assert "Tool Routing" in CONTEXT_MODE_NUDGE or "tool" in CONTEXT_MODE_NUDGE.lower()

    def test_nudge_has_output_style_section(self):
        """Test that nudge has output style guidance."""
        assert "Output Style" in CONTEXT_MODE_NUDGE or "terse" in CONTEXT_MODE_NUDGE.lower()

    def test_short_nudge_is_shorter(self):
        """Test that short nudge is significantly shorter than full nudge."""
        assert len(CONTEXT_MODE_NUDGE_SHORT) < len(CONTEXT_MODE_NUDGE)
        # Short nudge should be roughly half the size
        assert len(CONTEXT_MODE_NUDGE_SHORT) < len(CONTEXT_MODE_NUDGE) * 0.7

    def test_short_nudge_has_key_rules(self):
        """Test that short nudge retains key rules."""
        assert "CONTEXT-MODE RULES" in CONTEXT_MODE_NUDGE_SHORT
        assert "ctx_execute" in CONTEXT_MODE_NUDGE_SHORT
        assert "ctx_fetch" in CONTEXT_MODE_NUDGE_SHORT

    def test_nudge_token_count_estimate(self):
        """Test nudge token count is reasonable (~115 for full, ~50 for short)."""
        # Rough estimate: 4 chars per token average
        full_tokens = len(CONTEXT_MODE_NUDGE) / 4
        short_tokens = len(CONTEXT_MODE_NUDGE_SHORT) / 4
        assert 80 < full_tokens < 150  # ~115 target
        assert 30 < short_tokens < 70  # ~50 target
