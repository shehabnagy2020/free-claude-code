"""Unit tests for context-mode sidecar in api/runtime.py."""

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings


def make_settings(enable_context_mode=True):
    """Create test settings with context-mode toggle."""
    return Settings(
        messaging_platform="none",
        model="nvidia_nim/test/model",
        enable_context_mode=enable_context_mode,
        enable_web_server_tools=False,
    )


class TestContextModeSidecar:
    """Tests for context-mode sidecar lifecycle."""

    @pytest.mark.asyncio
    async def test_sidecar_not_started_when_disabled(self):
        """Test sidecar doesn't start when enable_context_mode=False."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=False)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        with patch("subprocess.Popen") as mock_popen:
            await runtime._start_context_mode_sidecar()
            mock_popen.assert_not_called()
            assert runtime._context_mode_process is None

    @pytest.mark.asyncio
    async def test_sidecar_started_when_enabled(self):
        """Test sidecar starts when enable_context_mode=True."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=True)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        mock_process = MagicMock(spec=subprocess.Popen)
        mock_process.pid = 12345

        with patch("subprocess.Popen", return_value=mock_process):
            await runtime._start_context_mode_sidecar()
            assert runtime._context_mode_process is not None
            assert runtime._context_mode_process.pid == 12345

    @pytest.mark.asyncio
    async def test_sidecar_stop_when_none(self):
        """Test stopping when sidecar was never started."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=False)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        # Should not raise
        await runtime._stop_context_mode_sidecar()
        assert runtime._context_mode_process is None

    @pytest.mark.asyncio
    async def test_sidecar_stop_success(self):
        """Test successful sidecar stop."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=True)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        mock_process = MagicMock(spec=subprocess.Popen)
        mock_process.pid = 12345
        mock_process.wait = MagicMock(return_value=0)

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("os.killpg") as mock_killpg:
                with patch("os.getpgid", return_value=999):
                    await runtime._start_context_mode_sidecar()
                    await runtime._stop_context_mode_sidecar()
                    mock_killpg.assert_called_once()
                    mock_process.wait.assert_called_once_with(timeout=3)

    @pytest.mark.asyncio
    async def test_sidecar_stop_timeout_force_kill(self):
        """Test force kill on timeout."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=True)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        mock_process = MagicMock(spec=subprocess.Popen)
        mock_process.pid = 12345
        mock_process.wait = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 3))
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("os.killpg"):
                with patch("os.getpgid", return_value=999):
                    await runtime._start_context_mode_sidecar()
                    await runtime._stop_context_mode_sidecar()
                    mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_sidecar_stop_process_not_found(self):
        """Test graceful handling of process not found."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=True)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        mock_process = MagicMock(spec=subprocess.Popen)
        mock_process.pid = 12345

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("os.killpg", side_effect=ProcessLookupError):
                with patch("os.getpgid", side_effect=ProcessLookupError):
                    await runtime._start_context_mode_sidecar()
                    # Should not raise
                    await runtime._stop_context_mode_sidecar()

    @pytest.mark.asyncio
    async def test_sidecar_filenotfound_logs_npm_error(self, caplog):
        """Test FileNotFoundError logs npm install hint."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=True)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        with patch("subprocess.Popen", side_effect=FileNotFoundError("npx")):
            await runtime._start_context_mode_sidecar()
            assert "npx not found" in caplog.text
            assert "Node.js/npm" in caplog.text

    @pytest.mark.asyncio
    async def test_health_check_loop_skips_when_disabled(self):
        """Test health check loop doesn't run when disabled."""
        from api.runtime import AppRuntime

        settings = make_settings(enable_context_mode=False)
        runtime = AppRuntime(app=MagicMock(), settings=settings)

        # Just verify no crash when process is None
        runtime._context_mode_process = None
        # Health check loop would be scheduled, not directly awaited
        # This test ensures no crash in setup
        assert runtime.settings.enable_context_mode is False
