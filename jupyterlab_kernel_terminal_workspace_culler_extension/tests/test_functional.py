"""Functional tests: a real Jupyter server, real terminado terminals, real
workspace files on disk, and the CLI talking to that server over HTTP.

Only time is faked - a terminal's ``last_activity`` and a workspace file's mtime
are moved into the past - so a cull pass runs exactly as it would after days of
idling.
"""

import asyncio
import json
import os
import signal
import time
from datetime import timedelta

import pytest
from jupyter_server._tz import utcnow
from jupyterlab_server.workspaces_handler import WORKSPACE_EXTENSION, slugify

from jupyterlab_kernel_terminal_workspace_culler_extension import cli, routes

EIGHT_DAYS = timedelta(days=8)
TWO_HOURS = timedelta(hours=2)


@pytest.fixture
def workspaces_dir(tmp_path, monkeypatch):
    path = tmp_path / "workspaces"
    path.mkdir()
    # read by jupyterlab's get_workspaces_dir(), which the culler falls back to
    # when no JupyterLab app is loaded in the server
    monkeypatch.setenv("JUPYTERLAB_WORKSPACES_DIR", str(path))
    return path


@pytest.fixture
def jp_server_config(workspaces_dir):
    return {
        "ServerApp": {
            "jpserver_extensions": {
                "jupyter_server_terminals": True,
                "jupyterlab_kernel_terminal_workspace_culler_extension": True,
            },
            "terminado_settings": {"shell_command": ["/bin/bash", "--norc", "--noprofile"]},
        }
    }


@pytest.fixture
def orphans():
    """PIDs of processes a test leaves holding a pty; killed at teardown."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _write_workspace(directory, ws_id, terminals=(), age=timedelta(0)):
    """A workspace file as JupyterLab saves it, last modified ``age`` ago."""
    path = directory / (slugify(ws_id) + WORKSPACE_EXTENSION)
    data = {f"terminal:{name}": {"data": {"name": name}} for name in terminals}
    path.write_text(json.dumps({"data": data, "metadata": {"id": ws_id}}))
    mtime = time.time() - age.total_seconds()
    os.utime(path, (mtime, mtime))
    return path


async def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


async def _new_terminal(jp_fetch, terminal_manager):
    """Start a real terminal and wait until its shell has printed a prompt."""
    response = await jp_fetch("api", "terminals", method="POST", body="{}")
    name = json.loads(response.body)["name"]
    term = terminal_manager.terminals[name]
    await _wait_for(lambda: len(term.read_buffer) > 0)
    await asyncio.sleep(0.3)  # let the prompt output settle
    return name, term


async def _idle(term, age):
    """Move the terminal's last activity ``age`` into the past, once it is quiet."""
    await asyncio.sleep(0.3)
    term.last_activity = utcnow() - age


def _culler():
    return routes.get_culler()


async def _send_settings(jp_fetch):
    """What the frontend does when a page loads: POST the user's settings."""
    await jp_fetch(
        "jupyterlab-kernel-terminal-workspace-culler-extension",
        "settings",
        method="POST",
        body="{}",
    )


def _terminal_manager(jp_serverapp):
    return jp_serverapp.web_app.settings["terminal_manager"]


async def test_named_workspaces_culled_default_kept(jp_fetch, workspaces_dir):
    """DEF-WSPACE-23: named and auto workspaces past the timeout are deleted;
    default is kept, and so is anything used recently."""
    await _send_settings(jp_fetch)
    default = _write_workspace(workspaces_dir, "default", age=EIGHT_DAYS)
    auto = _write_workspace(workspaces_dir, "auto-q", age=EIGHT_DAYS)
    named = _write_workspace(workspaces_dir, "probe", age=EIGHT_DAYS)
    recent = _write_workspace(workspaces_dir, "shot", age=timedelta(days=1))

    await _culler()._cull_idle_resources()

    assert default.exists()
    assert recent.exists()
    assert not auto.exists()
    assert not named.exists()


async def test_culled_named_workspace_releases_its_terminal(
    jp_fetch, jp_serverapp, workspaces_dir
):
    """The cascade runs through named workspaces too: one pass deletes the
    workspace and then the terminal only it referenced."""
    terminal_manager = _terminal_manager(jp_serverapp)
    name, term = await _new_terminal(jp_fetch, terminal_manager)
    probe = _write_workspace(workspaces_dir, "probe", terminals=[name], age=EIGHT_DAYS)
    await _idle(term, TWO_HOURS)
    await _send_settings(jp_fetch)

    await _culler()._cull_idle_resources()

    assert not probe.exists()
    assert name not in terminal_manager.terminals
    assert not term.ptyproc.isalive()


async def test_maximum_idle_ends_open_referenced_terminal(
    jp_fetch, jp_ws_fetch, jp_serverapp, workspaces_dir
):
    """Past terminalCullMaxIdleTimeout an open tab and a workspace reference no
    longer protect a terminal; below it they still do."""
    terminal_manager = _terminal_manager(jp_serverapp)
    old_name, old_term = await _new_terminal(jp_fetch, terminal_manager)
    young_name, young_term = await _new_terminal(jp_fetch, terminal_manager)
    _write_workspace(workspaces_dir, "default", terminals=[old_name, young_name])
    old_ws = await jp_ws_fetch("terminals", "websocket", old_name)
    young_ws = await jp_ws_fetch("terminals", "websocket", young_name)
    await _wait_for(lambda: old_term.clients and young_term.clients)
    await _idle(old_term, EIGHT_DAYS)
    await _idle(young_term, TWO_HOURS)

    culled = await _culler()._cull_terminals()

    assert culled == [old_name]
    assert old_name not in terminal_manager.terminals
    assert young_name in terminal_manager.terminals
    old_ws.close()
    young_ws.close()


async def test_cli_reports_defunct_terminal_removed(
    jp_fetch, jp_serverapp, jp_http_port, jp_base_url, jp_auth_header, orphans, tmp_path
):
    """DEF-CLI-22: a terminal whose shell died while an orphan still holds its pty
    is removed by `cull`, printed as culled, and gone from the next listing."""
    terminal_manager = _terminal_manager(jp_serverapp)
    name, term = await _new_terminal(jp_fetch, terminal_manager)
    pid_file = tmp_path / "orphan.pid"
    # a background job that ignores SIGHUP keeps the pty slave open after the
    # shell exits, so terminado never reads EOF (DEF-TERM-21)
    term.ptyproc.write(f"(trap '' HUP; exec sleep 600) & echo $! > {pid_file}\n")
    await _wait_for(lambda: pid_file.exists() and pid_file.read_text().strip())
    orphans.append(int(pid_file.read_text()))
    await _idle(term, TWO_HOURS)

    server_url = f"http://127.0.0.1:{jp_http_port}{jp_base_url}"
    token = jp_auth_header["Authorization"].split(" ", 1)[1]
    argv = ["--server-url", server_url, "--token", token, "cull", "--json",
            "--terminal-timeout", "60", "--workspace-timeout", "10080"]
    output_path = tmp_path / "cli.json"

    def run_cli():
        # the CLI blocks on HTTP; run it off the event loop that serves it
        import contextlib
        with open(output_path, "w") as out, contextlib.redirect_stdout(out):
            return cli.main(argv)

    rc = await asyncio.to_thread(run_cli)

    result = json.loads(output_path.read_text())
    assert rc == 0
    assert result["terminals_culled"] == [
        {"name": name, "idle_time": result["terminals_culled"][0]["idle_time"], "action": "culled"}
    ]
    listing = json.loads((await jp_fetch("api", "terminals")).body)
    assert name not in [t["name"] for t in listing]
    os.kill(orphans[0], 0)  # the orphan itself is left running, as documented
