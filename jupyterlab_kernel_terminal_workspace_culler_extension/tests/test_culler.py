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
    app.terminal_manager.terminals = {}  # real dict: name -> PtyWithClients
    app.terminal_manager.terminate = AsyncMock()

    return app


@pytest.fixture
def culler(mock_server_app):
    """Create a ResourceCuller with a mocked server app and workspace manager.

    The workspace manager is pre-mocked (no workspaces) so the property never
    resolves the real workspaces directory of the machine running the tests.
    """
    c = ResourceCuller(mock_server_app)
    ws_mgr = MagicMock()
    ws_mgr.list_workspaces.return_value = []
    c._workspace_manager = ws_mgr
    return c


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

    def test_bad_type_rejected_without_partial_apply(self, culler):
        """DEF-14: a payload with one bad value must change nothing at all."""
        with pytest.raises(ValueError):
            culler.update_settings({
                "kernelCullEnabled": False,
                "kernelCullIdleTimeout": "abc",
            })
        settings = culler.get_settings()
        assert settings["kernelCullEnabled"] is True  # untouched
        assert settings["kernelCullIdleTimeout"] == 60

    def test_bool_string_rejected(self, culler):
        with pytest.raises(ValueError):
            culler.update_settings({"terminalCullEnabled": "false"})
        assert culler.get_settings()["terminalCullEnabled"] is True

    def test_bool_rejected_for_int_setting(self, culler):
        with pytest.raises(ValueError):
            culler.update_settings({"cullCheckInterval": True})
        assert culler.get_settings()["cullCheckInterval"] == 5

    def test_unknown_keys_ignored(self, culler):
        culler.update_settings({"showNotifications": True, "bogus": 1})
        assert culler.get_settings()["kernelCullEnabled"] is True


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


def _pty_with_clients(n_clients: int) -> MagicMock:
    """Fake terminado PtyWithClients carrying n attached websocket clients."""
    pty = MagicMock()
    pty.clients = [MagicMock() for _ in range(n_clients)]
    return pty


class TestWebsocketTabProtection:
    """DEF-9: a live websocket client protects a terminal even when frontend
    reports are absent or stale (browser-throttled background tab)."""

    @pytest.mark.asyncio
    async def test_ws_connected_terminal_not_culled_without_reports(
        self, culler, mock_server_app
    ):
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        mock_server_app.terminal_manager.terminals = {
            terminal_name: _pty_with_clients(1)
        }

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_connected_terminal_not_culled_with_stale_reports(
        self, culler, mock_server_app
    ):
        """Reports stale past the TTL, but the websocket is still attached."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)
        stale_minutes = culler._cull_check_interval * culler._ACTIVE_TERMINAL_STALE_INTERVALS + 1
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        mock_server_app.terminal_manager.terminals = {
            terminal_name: _pty_with_clients(1)
        }
        culler._active_terminals_by_client["A"] = ({terminal_name}, stale_time)

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_without_ws_clients_culled(self, culler, mock_server_app):
        """Terminal exists in the registry but has zero attached websockets."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        mock_server_app.terminal_manager.terminals = {
            terminal_name: _pty_with_clients(0)
        }

        culled = await culler._cull_terminals()

        assert terminal_name in culled

    def test_connection_status_reflects_ws_clients(self, culler, mock_server_app):
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1"},
            {"name": "2"},
        ]
        mock_server_app.terminal_manager.terminals = {
            "1": _pty_with_clients(1),
            "2": _pty_with_clients(0),
        }

        status = culler.get_terminals_connection_status()

        assert status == {"1": True, "2": False}

    def test_manager_without_registry_falls_back_to_reports(
        self, culler, mock_server_app
    ):
        """A terminal manager without a .terminals dict must not break the check."""
        mock_server_app.terminal_manager.terminals = None
        culler.set_active_terminals(["1"], client_id="A")

        assert culler._terminal_has_active_tab("1") is True
        assert culler._terminal_has_active_tab("2") is False


class TestWorkspaceTerminalProtection:
    """A terminal referenced by any not-yet-culled workspace is NEVER culled;
    culling the workspace releases it (the cascade)."""

    @staticmethod
    def _ws(ws_id: str, terminal_names: list[str], idle_days: int = 10) -> dict:
        old = (datetime.now(timezone.utc) - timedelta(days=idle_days)).isoformat()
        return {
            "data": {f"terminal:{n}": {} for n in terminal_names},
            "metadata": {"id": ws_id, "last_modified": old},
        }

    @pytest.mark.asyncio
    async def test_workspace_referenced_terminal_never_culled(
        self, culler, mock_server_app
    ):
        """Idle, no tab, no reports - but the default workspace references it."""
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": idle_time}
        ]
        culler._workspace_manager.list_workspaces.return_value = [
            self._ws("default", ["1"])
        ]

        culled = await culler._cull_terminals()

        assert culled == []
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_listing_failure_fails_safe(self, culler, mock_server_app):
        """If workspace references cannot be verified, cull no terminals."""
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": idle_time}
        ]
        culler._workspace_manager.list_workspaces.side_effect = OSError("boom")

        culled = await culler._cull_terminals()

        assert culled == []
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_cascade_workspace_culled_then_terminal(
        self, culler, mock_server_app
    ):
        """An idle auto-* workspace is culled first; the terminal only it
        referenced is culled in the same pass."""
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": idle_time}
        ]
        workspaces = [self._ws("auto-0", ["1"])]
        ws_mgr = culler._workspace_manager
        ws_mgr.list_workspaces.side_effect = lambda: list(workspaces)
        ws_mgr.delete.side_effect = lambda ws_id: workspaces.clear()

        await culler._cull_idle_resources()

        ws_mgr.delete.assert_called_once_with("auto-0")
        mock_server_app.terminal_manager.terminate.assert_called_once_with("1")

    @pytest.mark.asyncio
    async def test_cascade_blocked_by_surviving_workspace(
        self, culler, mock_server_app
    ):
        """The culled workspace's terminal survives when another workspace
        that is not culled still references it."""
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": idle_time}
        ]
        workspaces = [self._ws("auto-0", ["1"]), self._ws("default", ["1"])]
        ws_mgr = culler._workspace_manager
        ws_mgr.list_workspaces.side_effect = lambda: list(workspaces)
        ws_mgr.delete.side_effect = lambda ws_id: workspaces.pop(0)

        await culler._cull_idle_resources()

        ws_mgr.delete.assert_called_once_with("auto-0")
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_survives_reference_loss(self, culler, mock_server_app):
        """An open-tab (and workspace-referenced) terminal must anchor its grace
        while alive, so losing the reference (tab closed, workspace culled)
        grants the full idle timeout - not a cull on the next pass."""
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=240)
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": idle_time}
        ]
        # Pass 1: tab open (ws client) AND referenced by the default workspace
        mock_server_app.terminal_manager.terminals = {"1": _pty_with_clients(1)}
        culler._workspace_manager.list_workspaces.return_value = [
            self._ws("default", ["1"])
        ]
        culled = await culler._cull_terminals()
        assert culled == []
        assert "1" in culler._terminal_tab_last_seen  # grace anchor stamped

        # Pass 2: tab closed and reference gone - grace must protect it
        mock_server_app.terminal_manager.terminals = {"1": _pty_with_clients(0)}
        culler._workspace_manager.list_workspaces.return_value = []
        culled = await culler._cull_terminals()
        assert culled == []
        mock_server_app.terminal_manager.terminate.assert_not_called()

    def test_connection_status_includes_workspace_reference(
        self, culler, mock_server_app
    ):
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1"},
            {"name": "2"},
        ]
        mock_server_app.terminal_manager.terminals = {}
        culler._workspace_manager.list_workspaces.return_value = [
            self._ws("default", ["1"], idle_days=0)
        ]

        status = culler.get_terminals_connection_status()

        assert status == {"1": True, "2": False}


class TestDisconnectGrace:
    """DEF-12: a terminal whose tab closed/disconnected gets a fresh idle
    timeout from that moment, so a transient websocket loss cannot cull it."""

    @pytest.mark.asyncio
    async def test_recently_disconnected_terminal_not_culled(
        self, culler, mock_server_app
    ):
        """Idle 120 min, but the tab was still open 5 min ago."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=120)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        culler._terminal_tab_last_seen[terminal_name] = datetime.now(
            timezone.utc
        ) - timedelta(minutes=5)

        culled = await culler._cull_terminals()

        assert terminal_name not in culled
        mock_server_app.terminal_manager.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_expires_after_full_timeout(self, culler, mock_server_app):
        """Tab last seen 90 min ago with a 60 min timeout - grace is spent."""
        terminal_name = "terminal-1"
        idle_time = datetime.now(timezone.utc) - timedelta(minutes=240)

        mock_server_app.terminal_manager.list.return_value = [
            {"name": terminal_name, "last_activity": idle_time}
        ]
        culler._terminal_tab_last_seen[terminal_name] = datetime.now(
            timezone.utc
        ) - timedelta(minutes=90)

        culled = await culler._cull_terminals()

        assert terminal_name in culled

    @pytest.mark.asyncio
    async def test_tab_last_seen_recorded_and_pruned(self, culler, mock_server_app):
        """An active tab stamps last-seen; vanished terminals are forgotten."""
        mock_server_app.terminal_manager.list.return_value = [
            {"name": "1", "last_activity": datetime.now(timezone.utc)}
        ]
        mock_server_app.terminal_manager.terminals = {"1": _pty_with_clients(1)}
        culler._terminal_tab_last_seen["gone"] = datetime.now(timezone.utc)

        await culler._cull_terminals()

        assert "1" in culler._terminal_tab_last_seen
        assert "gone" not in culler._terminal_tab_last_seen


class TestWorkspacesDirResolution:
    """DEF-11: the culler must use the workspaces dir the live server uses."""

    def test_extension_app_trait_wins(self, culler, mock_server_app, tmp_path):
        lab_app = MagicMock()
        lab_app.workspaces_dir = str(tmp_path / "ws")
        mock_server_app.extension_manager.extension_apps = {"lab": {lab_app}}

        assert culler._resolve_workspaces_dir() == tmp_path / "ws"

    def test_env_var_honoured_without_trait(
        self, culler, mock_server_app, tmp_path, monkeypatch
    ):
        mock_server_app.extension_manager = None
        monkeypatch.setenv("JUPYTERLAB_WORKSPACES_DIR", str(tmp_path / "envws"))

        assert culler._resolve_workspaces_dir() == tmp_path / "envws"


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
        culler._active_terminals_by_client["A"] = ({"1"}, stale_time, culler._cull_check_interval)

        assert culler._terminal_has_active_tab("1") is False
        assert "A" not in culler._active_terminals_by_client

    def test_client_judged_against_own_interval(self, culler):
        """A client on a slower cadence than the server interval stays fresh.

        DEF-13: after an interval change the backend must not expire clients
        that still report at their previously configured (slower) cadence.
        """
        client_interval = 30  # minutes; server default is 5
        age_minutes = culler._cull_check_interval * culler._ACTIVE_TERMINAL_STALE_INTERVALS + 5
        reported_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        culler._active_terminals_by_client["A"] = ({"1"}, reported_at, client_interval)

        assert culler._terminal_has_active_tab("1") is True

    def test_set_active_terminals_prunes_stale_clients(self, culler):
        """DEF-15: every report prunes, so the per-client map stays bounded."""
        stale_minutes = culler._cull_check_interval * culler._ACTIVE_TERMINAL_STALE_INTERVALS + 1
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        culler._active_terminals_by_client["old"] = ({"1"}, stale_time, culler._cull_check_interval)

        culler.set_active_terminals(["2"], client_id="new")

        assert "old" not in culler._active_terminals_by_client
        assert "new" in culler._active_terminals_by_client

    def test_bogus_report_interval_falls_back_to_server_interval(self, culler):
        culler.set_active_terminals(["1"], client_id="A", interval_minutes=0)
        culler.set_active_terminals(["2"], client_id="B", interval_minutes="60")
        assert culler._active_terminals_by_client["A"][2] == culler._cull_check_interval
        assert culler._active_terminals_by_client["B"][2] == culler._cull_check_interval


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
