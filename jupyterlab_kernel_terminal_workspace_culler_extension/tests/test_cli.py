"""Unit tests for the CLI culling logic."""

import argparse
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from jupyterlab_kernel_terminal_workspace_culler_extension.cli import (
    cmd_cull,
    resolve_server_url_and_token,
)


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "json": False,
        "dry_run": False,
        "kernel_timeout": 60,
        "terminal_timeout": 60,
        "workspace_timeout": 10080,
        "include_connected": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _client(terminals, connection):
    client = MagicMock()
    client.list_kernels.return_value = []
    client.list_terminals.return_value = terminals
    client.get_terminals_connection.return_value = connection
    client.cull_workspaces.return_value = []
    client.terminate_terminal.return_value = True
    return client


def _idle_terminal(name: str, idle_minutes: int) -> dict:
    last = datetime.now(timezone.utc) - timedelta(minutes=idle_minutes)
    return {
        "name": name,
        "last_activity": last.isoformat(),
        "idle_seconds": idle_minutes * 60,
        "idle_time": f"{idle_minutes}m",
    }


class TestCmdCullFailClosed:
    """DEF-10: an unavailable connection endpoint must never cull terminals."""

    def test_endpoint_failure_skips_terminal_culling(self, capsys):
        client = _client([_idle_terminal("1", 120)], connection=None)

        rc = cmd_cull(client, _args())

        client.terminate_terminal.assert_not_called()
        assert rc == 1
        assert "connection status" in capsys.readouterr().err

    def test_connected_terminal_skipped(self, capsys):
        client = _client([_idle_terminal("1", 120)], connection={"1": True})

        rc = cmd_cull(client, _args())

        client.terminate_terminal.assert_not_called()
        assert rc == 0

    def test_disconnected_idle_terminal_culled(self, capsys):
        client = _client([_idle_terminal("1", 120)], connection={"1": False})

        rc = cmd_cull(client, _args())

        client.terminate_terminal.assert_called_once_with("1")
        assert rc == 0

    def test_include_connected_bypasses_check(self, capsys):
        client = _client([_idle_terminal("1", 120)], connection=None)

        rc = cmd_cull(client, _args(include_connected=True))

        client.get_terminals_connection.assert_not_called()
        client.terminate_terminal.assert_called_once_with("1")
        assert rc == 0

    def test_workspace_endpoint_failure_is_an_error(self, capsys):
        """DEF-18: unavailable workspace culling is an error, not 'nothing to cull'."""
        client = _client([], connection={})
        client.cull_workspaces.return_value = None

        rc = cmd_cull(client, _args())

        assert rc == 1
        assert "workspaces" in capsys.readouterr().err


class TestServerResolution:
    """DEF-20: JUPYTER_SERVER_URL was documented but never read."""

    def _ns(self, server_url=None, token=None):
        return argparse.Namespace(server_url=server_url, token=token)

    def test_flag_wins(self, monkeypatch):
        monkeypatch.setenv("JUPYTER_SERVER_URL", "http://env:8888/")
        url, token = resolve_server_url_and_token(
            self._ns(server_url="http://flag:8888/", token="t1")
        )
        assert url == "http://flag:8888/"
        assert token == "t1"

    def test_flag_url_falls_back_to_env_token(self, monkeypatch):
        """--server-url without --token still authenticates via JUPYTER_TOKEN."""
        monkeypatch.setenv("JUPYTER_TOKEN", "envtoken")
        monkeypatch.delenv("JUPYTERHUB_API_TOKEN", raising=False)
        monkeypatch.delenv("JPY_API_TOKEN", raising=False)
        url, token = resolve_server_url_and_token(
            self._ns(server_url="http://flag:8888/")
        )
        assert url == "http://flag:8888/"
        assert token == "envtoken"

    def test_env_var_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("JUPYTER_SERVER_URL", "http://env:8888/")
        monkeypatch.setenv("JUPYTER_TOKEN", "envtoken")
        monkeypatch.delenv("JUPYTERHUB_API_TOKEN", raising=False)
        monkeypatch.delenv("JPY_API_TOKEN", raising=False)
        url, token = resolve_server_url_and_token(self._ns())
        assert url == "http://env:8888/"
        assert token == "envtoken"
