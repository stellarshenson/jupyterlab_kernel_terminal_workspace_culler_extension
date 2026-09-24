"""Unit tests for the CLI culling logic."""

import argparse
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

from jupyterlab_kernel_terminal_workspace_culler_extension.cli import (
    JupyterClient,
    cmd_cull,
    cmd_list,
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


class TestTerminateReportsRemoval:
    """DEF-CLI-22: culled means the server removed the terminal from its registry."""

    @staticmethod
    def _response(payload=None, status=200):
        response = MagicMock()
        response.json.return_value = payload
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(str(status))
        return response

    def test_goes_through_the_extension_route(self):
        client = JupyterClient("http://127.0.0.1:8888/", "tok")
        with patch("requests.post", return_value=self._response({"removed": True})) as post:
            assert client.terminate_terminal("3") is True

        url = post.call_args.args[0]
        assert url.endswith("jupyterlab-kernel-terminal-workspace-culler-extension/cull-terminal")
        assert post.call_args.kwargs["json"] == {"name": "3"}

    def test_terminal_still_registered_is_a_failure(self):
        client = JupyterClient("http://127.0.0.1:8888/")
        with patch("requests.post", return_value=self._response({"removed": False})):
            assert client.terminate_terminal("3") is False

    def test_route_error_is_a_failure(self):
        client = JupyterClient("http://127.0.0.1:8888/")
        with patch("requests.post", return_value=self._response(status=404)):
            assert client.terminate_terminal("3") is False

    def test_failure_printed_as_failed(self, capsys):
        client = _client([_idle_terminal("3", 120)], connection={"3": False})
        client.terminate_terminal.return_value = False

        cmd_cull(client, _args())

        assert "3  idle: 120m  (failed)" in capsys.readouterr().out


class TestListProtectedLabel:
    """The protected label is the server's rule, not a copy of it in the CLI."""

    def test_only_server_protected_workspaces_marked(self, capsys):
        client = _client([], connection={})
        client.get_culler_status.return_value = None
        client.list_workspaces.return_value = [
            {"id": wid, "protected": wid == "default", "idle_time": "8.0d"}
            for wid in ("auto-0", "default", "probe")
        ]

        cmd_list(client, argparse.Namespace(json=False))

        lines = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()
                 if line.startswith("  ") and "idle:" in line}
        assert "(protected)" in lines["default"]
        assert "(protected)" not in lines["auto-0"]
        assert "(protected)" not in lines["probe"]


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
