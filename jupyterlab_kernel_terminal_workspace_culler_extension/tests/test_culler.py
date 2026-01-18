"""Unit tests for the resource culler."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jupyterlab_kernel_terminal_workspace_culler_extension.culler import ResourceCuller


@pytest.fixture
def mock_server_app():
    """Create a mock server app with kernel, terminal, and session managers."""
    app = MagicMock()

    # Mock kernel manager
    app.kernel_manager = MagicMock()
    app.kernel_manager.list_kernel_ids.return_value = []
    app.kernel_manager.get_kernel.return_value = None
    app.kernel_manager.shutdown_kernel = AsyncMock()

    # Mock terminal manager
    app.terminal_manager = MagicMock()
    app.terminal_manager.list.return_value = []
    app.terminal_manager.terminate = AsyncMock()

    # Mock session manager
    app.session_manager = MagicMock()
    app.session_manager.list_sessions = AsyncMock(return_value=[])
    app.session_manager.delete_session = AsyncMock()

    return app


@pytest.fixture
def culler(mock_server_app):
    """Create a ResourceCuller instance with mocked server app."""
    return ResourceCuller(mock_server_app)


class TestDefaultSettings:
    """Test default settings initialization."""

    def test_default_kernel_settings(self, culler):
        """Verify default kernel culling settings."""
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is True
        assert settings["kernelCullIdleTimeout"] == 60  # 1 hour

    def test_default_terminal_settings(self, culler):
        """Verify default terminal culling settings."""
        settings = culler.get_settings()
        assert settings["terminalCullEnabled"] is True
        assert settings["terminalCullIdleTimeout"] == 60  # 1 hour

    def test_default_session_settings(self, culler):
        """Verify default session culling settings."""
        settings = culler.get_settings()
        assert settings["sessionCullEnabled"] is False
        assert settings["sessionCullIdleTimeout"] == 10080  # 7 days

    def test_default_check_interval(self, culler):
        """Verify default check interval."""
        settings = culler.get_settings()
        assert settings["cullCheckInterval"] == 5


class TestUpdateSettings:
    """Test settings update functionality."""

    def test_update_kernel_settings(self, culler):
        """Test updating kernel culling settings."""
        culler.update_settings({
            "kernelCullEnabled": False,
            "kernelCullIdleTimeout": 120
        })
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is False
        assert settings["kernelCullIdleTimeout"] == 120

    def test_update_terminal_settings(self, culler):
        """Test updating terminal culling settings."""
        culler.update_settings({
            "terminalCullEnabled": False,
            "terminalCullIdleTimeout": 45
        })
        settings = culler.get_settings()
        assert settings["terminalCullEnabled"] is False
        assert settings["terminalCullIdleTimeout"] == 45

    def test_update_session_settings(self, culler):
        """Test updating session culling settings."""
        culler.update_settings({
            "sessionCullEnabled": True,
            "sessionCullIdleTimeout": 60
        })
        settings = culler.get_settings()
        assert settings["sessionCullEnabled"] is True
        assert settings["sessionCullIdleTimeout"] == 60

    def test_partial_update(self, culler):
        """Test that partial updates don't affect other settings."""
        culler.update_settings({"kernelCullEnabled": False})
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is False
        # Other settings should remain at defaults
        assert settings["terminalCullEnabled"] is True
        assert settings["sessionCullEnabled"] is False


class TestCullIdleKernel:
    """Test kernel culling functionality."""

    @pytest.mark.asyncio
    async def test_cull_idle_kernel(self, culler, mock_server_app):
        """Test that idle kernel exceeding timeout gets culled."""
        kernel_id = "test-kernel-123"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_kernel = MagicMock()
        mock_kernel.execution_state = "idle"
        mock_kernel.last_activity = idle_time

        mock_server_app.kernel_manager.list_kernel_ids.return_value = [kernel_id]
        mock_server_app.kernel_manager.get_kernel.return_value = mock_kernel

        culled = await culler._cull_kernels()

        assert kernel_id in culled
        mock_server_app.kernel_manager.shutdown_kernel.assert_called_once_with(kernel_id)

    @pytest.mark.asyncio
    async def test_skip_busy_kernel(self, culler, mock_server_app):
        """Test that busy kernels are not culled."""
        kernel_id = "busy-kernel-123"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_kernel = MagicMock()
        mock_kernel.execution_state = "busy"
        mock_kernel.last_activity = idle_time

        mock_server_app.kernel_manager.list_kernel_ids.return_value = [kernel_id]
        mock_server_app.kernel_manager.get_kernel.return_value = mock_kernel

        culled = await culler._cull_kernels()

        assert kernel_id not in culled
        mock_server_app.kernel_manager.shutdown_kernel.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_active_kernel(self, culler, mock_server_app):
        """Test that recently active kernels are not culled."""
        kernel_id = "active-kernel-123"
        # Last activity 5 minutes ago - below 60 minute threshold
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        mock_kernel = MagicMock()
        mock_kernel.execution_state = "idle"
        mock_kernel.last_activity = recent_time

        mock_server_app.kernel_manager.list_kernel_ids.return_value = [kernel_id]
        mock_server_app.kernel_manager.get_kernel.return_value = mock_kernel

        culled = await culler._cull_kernels()

        assert kernel_id not in culled
        mock_server_app.kernel_manager.shutdown_kernel.assert_not_called()


class TestCullIdleTerminal:
    """Test terminal culling functionality."""

    @pytest.mark.asyncio
    async def test_cull_idle_terminal(self, culler, mock_server_app):
        """Test that idle terminal exceeding timeout gets culled."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=60)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name in culled
        mock_server_app.terminal_manager.terminate.assert_called_once_with(terminal_name)

    @pytest.mark.asyncio
    async def test_skip_active_terminal(self, culler, mock_server_app):
        """Test that recently active terminals are not culled."""
        terminal_name = "terminal-1"
        # Last activity 5 minutes ago - below 30 minute threshold
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": recent_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_cull_terminal_with_iso_string(self, culler, mock_server_app):
        """Test culling terminal with ISO string timestamp."""
        terminal_name = "terminal-1"
        idle_time = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name in culled


class TestCullResult:
    """Test cull result retrieval."""

    def test_get_last_cull_result_empty(self, culler):
        """Test that initial cull result is empty."""
        result = culler.get_last_cull_result()
        assert result["kernels_culled"] == []
        assert result["terminals_culled"] == []
        assert result["sessions_culled"] == []

    def test_result_consumed_flag(self, culler):
        """Test that result is marked as consumed after retrieval."""
        # First call returns empty (result_consumed is True initially)
        result1 = culler.get_last_cull_result()

        # Simulate a culling that produced results
        culler._last_cull_result = {
            "kernels_culled": ["kernel-1"],
            "terminals_culled": [],
            "sessions_culled": [],
        }
        culler._result_consumed = False

        # First retrieval should return the result
        result2 = culler.get_last_cull_result()
        assert result2["kernels_culled"] == ["kernel-1"]

        # Second retrieval should return empty (consumed)
        result3 = culler.get_last_cull_result()
        assert result3["kernels_culled"] == []


class TestStatus:
    """Test status retrieval."""

    def test_status_not_running(self, culler):
        """Test status when culler is not running."""
        status = culler.get_status()
        assert status["running"] is False

    def test_status_running(self, culler):
        """Test status when culler is running."""
        with patch.object(culler, "_periodic_callback", MagicMock()):
            status = culler.get_status()
            assert status["running"] is True

    def test_status_includes_settings(self, culler):
        """Test that status includes current settings."""
        status = culler.get_status()
        assert "settings" in status
        assert "kernelCullEnabled" in status["settings"]
