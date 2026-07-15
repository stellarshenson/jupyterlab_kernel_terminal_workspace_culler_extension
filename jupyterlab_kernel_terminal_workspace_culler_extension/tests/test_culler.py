"""Unit tests for the resource culler."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jupyterlab_kernel_terminal_workspace_culler_extension.culler import ResourceCuller


@pytest.fixture
def mock_server_app():
    """Create a mock server app with kernel and terminal managers."""
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

    return app


@pytest.fixture
def culler(mock_server_app):
    """Create a ResourceCuller instance with mocked server app."""
    return ResourceCuller(mock_server_app)


class TestDefaultSettings:
    """Test default settings initialization."""

    def test_default_kernel_settings(self, culler):
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is True
        assert settings["kernelCullIdleTimeout"] == 60  # 1 hour

    def test_default_terminal_settings(self, culler):
        settings = culler.get_settings()
        assert settings["terminalCullEnabled"] is True
        assert settings["terminalCullIdleTimeout"] == 60  # 1 hour
        assert settings["terminalCullDisconnectedOnly"] is True

    def test_default_workspace_settings(self, culler):
        settings = culler.get_settings()
        assert settings["workspaceCullEnabled"] is True
        assert settings["workspaceCullIdleTimeout"] == 10080  # 7 days

    def test_default_check_interval(self, culler):
        settings = culler.get_settings()
        assert settings["cullCheckInterval"] == 5


class TestUpdateSettings:
    """Test settings update functionality."""

    def test_update_kernel_settings(self, culler):
        culler.update_settings({"kernelCullEnabled": False, "kernelCullIdleTimeout": 120})
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is False
        assert settings["kernelCullIdleTimeout"] == 120

    def test_update_terminal_settings(self, culler):
        culler.update_settings({"terminalCullEnabled": False, "terminalCullIdleTimeout": 45})
        settings = culler.get_settings()
        assert settings["terminalCullEnabled"] is False
        assert settings["terminalCullIdleTimeout"] == 45

    def test_update_workspace_settings(self, culler):
        culler.update_settings({"workspaceCullEnabled": False, "workspaceCullIdleTimeout": 1440})
        settings = culler.get_settings()
        assert settings["workspaceCullEnabled"] is False
        assert settings["workspaceCullIdleTimeout"] == 1440

    def test_partial_update(self, culler):
        culler.update_settings({"kernelCullEnabled": False})
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is False
        # Other settings remain at defaults
        assert settings["terminalCullEnabled"] is True
        assert settings["workspaceCullEnabled"] is True

    def test_clamp_timeouts_and_interval(self, culler):
        """DEF-5: server-side clamp - zero/negative values floor to 1."""
        culler.update_settings({
            "kernelCullIdleTimeout": 0,
            "terminalCullIdleTimeout": -5,
            "workspaceCullIdleTimeout": 0,
            "cullCheckInterval": 0,
        })
        settings = culler.get_settings()
        assert settings["kernelCullIdleTimeout"] == 1
        assert settings["terminalCullIdleTimeout"] == 1
        assert settings["workspaceCullIdleTimeout"] == 1
        assert settings["cullCheckInterval"] == 1


class TestCullIdleKernel:
    """Test kernel culling functionality."""

    @pytest.mark.asyncio
    async def test_cull_idle_kernel(self, culler, mock_server_app):
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
        kernel_id = "active-kernel-123"
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
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name in culled
        mock_server_app.terminal_manager.terminate.assert_called_once_with(terminal_name)

    @pytest.mark.asyncio
    async def test_skip_active_terminal(self, culler, mock_server_app):
        terminal_name = "terminal-1"
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": recent_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_cull_terminal_with_iso_string(self, culler, mock_server_app):
        terminal_name = "terminal-1"
        idle_time = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]

        culled = await culler._cull_terminals()

        assert terminal_name in culled

    @pytest.mark.asyncio
    async def test_connected_terminal_not_culled(self, culler, mock_server_app):
        """DEF-1: an idle terminal reported open by a client is protected."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        culler.set_active_terminals([terminal_name], client_id="A")

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_only_off_culls_connected(self, culler, mock_server_app):
        """With disconnected-only disabled, an idle terminal is culled regardless of tab."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        culler.set_active_terminals([terminal_name], client_id="A")
        culler.update_settings({"terminalCullDisconnectedOnly": False})

        culled = await culler._cull_terminals()

        assert terminal_name in culled


class TestActiveTerminals:
    """DEF-1: per-client active-terminal tracking with union and TTL."""

    def test_union_across_clients(self, culler):
        culler.set_active_terminals(["1"], client_id="A")
        culler.set_active_terminals(["2"], client_id="B")
        assert culler._terminal_has_active_tab("1") is True
        assert culler._terminal_has_active_tab("2") is True

    def test_empty_report_does_not_clobber(self, culler):
        """A second client's empty report must not wipe the first client's terminals."""
        culler.set_active_terminals(["1"], client_id="A")
        culler.set_active_terminals([], client_id="B")
        assert culler._terminal_has_active_tab("1") is True

    def test_stale_client_expires(self, culler):
        """A client silent beyond the TTL stops protecting its terminals and is pruned."""
        stale_minutes = culler._cull_check_interval * culler._ACTIVE_TERMINAL_STALE_INTERVALS + 1
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        culler._active_terminals_by_client["A"] = ({"1"}, stale_time)

        assert culler._terminal_has_active_tab("1") is False
        assert "A" not in culler._active_terminals_by_client


class TestCullWorkspaces:
    """DEF-2/DEF-4: only auto-* workspaces are cull-eligible."""

    def _ws_mgr(self, ids):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        ws_mgr = MagicMock()
        ws_mgr.list_workspaces.return_value = [
            {"metadata": {"id": wid, "last_modified": old}} for wid in ids
        ]
        return ws_mgr

    def test_cull_auto_only(self, culler):
        ws_mgr = self._ws_mgr(["auto-0", "default", "myproject"])
        culler._workspace_manager = ws_mgr

        culled = culler._cull_workspaces()

        assert culled == ["auto-0"]
        ws_mgr.delete.assert_called_once_with("auto-0")

    def test_default_never_culled(self, culler):
        ws_mgr = self._ws_mgr(["default", "/default"])
        culler._workspace_manager = ws_mgr

        culled = culler._cull_workspaces()

        assert culled == []
        ws_mgr.delete.assert_not_called()

    def test_named_workspace_preserved(self, culler):
        ws_mgr = self._ws_mgr(["myproject", "analysis"])
        culler._workspace_manager = ws_mgr

        culled = culler._cull_workspaces()

        assert culled == []
        ws_mgr.delete.assert_not_called()

    def test_recent_auto_not_culled(self, culler):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        ws_mgr = MagicMock()
        ws_mgr.list_workspaces.return_value = [
            {"metadata": {"id": "auto-0", "last_modified": recent}}
        ]
        culler._workspace_manager = ws_mgr

        culled = culler._cull_workspaces()

        assert culled == []
        ws_mgr.delete.assert_not_called()


class TestCullResult:
    """Test cull result retrieval."""

    def test_get_last_cull_result_empty(self, culler):
        result = culler.get_last_cull_result()
        assert result["kernels_culled"] == []
        assert result["terminals_culled"] == []
        assert result["workspaces_culled"] == []

    def test_result_consumed_flag(self, culler):
        # First call returns empty (result_consumed True initially)
        culler.get_last_cull_result()

        culler._last_cull_result = {
            "kernels_culled": ["kernel-1"],
            "terminals_culled": [],
            "workspaces_culled": [],
        }
        culler._result_consumed = False

        result2 = culler.get_last_cull_result()
        assert result2["kernels_culled"] == ["kernel-1"]

        result3 = culler.get_last_cull_result()
        assert result3["kernels_culled"] == []


class TestStatus:
    """Test status retrieval."""

    def test_status_not_running(self, culler):
        status = culler.get_status()
        assert status["running"] is False

    def test_status_running(self, culler):
        with patch.object(culler, "_periodic_callback", MagicMock()):
            status = culler.get_status()
            assert status["running"] is True

    def test_status_includes_settings(self, culler):
        status = culler.get_status()
        assert "settings" in status
        assert "kernelCullEnabled" in status["settings"]
