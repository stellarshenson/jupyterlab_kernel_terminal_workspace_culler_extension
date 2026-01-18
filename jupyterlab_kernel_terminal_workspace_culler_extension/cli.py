"""CLI for jupyterlab_kernel_terminal_workspace_culler_extension."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests


def get_jupyter_server_info() -> tuple[str, str | None]:
    """
    Auto-detect JupyterLab base URL and token.

    Checks in order:
    1. jupyter server list --json - query running servers (uses localhost)
    2. JUPYTERHUB_SERVICE_PREFIX - JupyterHub environment variable
    3. Default: http://localhost:8888

    Token priority (JupyterHub API token takes precedence for API access):
    1. JUPYTERHUB_API_TOKEN - required for JupyterHub API endpoints
    2. JPY_API_TOKEN - legacy JupyterHub token
    3. JUPYTER_TOKEN - standalone Jupyter server token
    4. Token from jupyter server list (fallback)

    Returns:
        Tuple of (base_url, token) where token may be None
    """
    # Get token - prioritize JupyterHub API token for proper API access
    token = (
        os.environ.get("JUPYTERHUB_API_TOKEN")
        or os.environ.get("JPY_API_TOKEN")
        or os.environ.get("JUPYTER_TOKEN")
    )

    # Try to detect from running Jupyter servers (preferred - always uses localhost)
    try:
        result = subprocess.run(
            ["jupyter", "server", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse first server (one JSON object per line)
            first_line = result.stdout.strip().split("\n")[0]
            server_info = json.loads(first_line)
            port = server_info.get("port", 8888)
            base_url = server_info.get("base_url", "/").rstrip("/")
            # Use server token as fallback if no env token
            if not token:
                token = server_info.get("token")
            return f"http://127.0.0.1:{port}{base_url}", token
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass  # Fall through to other methods

    # Check for JupyterHub environment
    service_prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX")
    if service_prefix:
        port = os.environ.get("JUPYTER_PORT", "8888")
        return f"http://127.0.0.1:{port}{service_prefix.rstrip('/')}", token

    # Default
    port = os.environ.get("JUPYTER_PORT", "8888")
    return f"http://localhost:{port}", token


def format_idle_time(last_activity: str | datetime | None) -> str:
    """Format idle time as human-readable string."""
    if last_activity is None:
        return "unknown"

    if isinstance(last_activity, str):
        last_activity = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))

    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    idle_seconds = (now - last_activity).total_seconds()

    if idle_seconds < 60:
        return f"{idle_seconds:.0f}s"
    elif idle_seconds < 3600:
        return f"{idle_seconds / 60:.1f}m"
    elif idle_seconds < 86400:
        return f"{idle_seconds / 3600:.1f}h"
    else:
        return f"{idle_seconds / 86400:.1f}d"


def format_idle_seconds(last_activity: str | datetime | None) -> float:
    """Get idle time in seconds."""
    if last_activity is None:
        return -1

    if isinstance(last_activity, str):
        last_activity = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))

    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return (now - last_activity).total_seconds()


class JupyterClient:
    """Client for Jupyter server REST API."""

    def __init__(self, server_url: str, token: str | None = None):
        self.server_url = server_url.rstrip("/") + "/"
        self.token = token
        self.headers = {"Authorization": f"token {token}"} if token else {}
        self.is_localhost = (
            server_url.startswith("http://localhost")
            or server_url.startswith("http://127.0.0.1")
            or server_url.startswith("http://[::1]")
        )

    def _get(self, endpoint: str) -> dict | list:
        url = urljoin(self.server_url, endpoint)
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def _delete(self, endpoint: str) -> bool:
        url = urljoin(self.server_url, endpoint)
        response = requests.delete(url, headers=self.headers, timeout=10)
        return response.status_code in (200, 204)

    def list_kernels(self) -> list[dict]:
        """List all kernels with their status."""
        kernels = self._get("api/kernels")
        result = []
        for k in kernels:
            result.append({
                "id": k.get("id"),
                "name": k.get("name"),
                "execution_state": k.get("execution_state"),
                "last_activity": k.get("last_activity"),
                "idle_seconds": format_idle_seconds(k.get("last_activity")),
                "idle_time": format_idle_time(k.get("last_activity")),
            })
        return result

    def list_terminals(self) -> list[dict]:
        """List all terminals with their status."""
        terminals = self._get("api/terminals")
        result = []
        for t in terminals:
            result.append({
                "name": t.get("name"),
                "last_activity": t.get("last_activity"),
                "idle_seconds": format_idle_seconds(t.get("last_activity")),
                "idle_time": format_idle_time(t.get("last_activity")),
            })
        return result

    def list_sessions(self) -> list[dict]:
        """List all sessions with their status."""
        sessions = self._get("api/sessions")
        result = []
        for s in sessions:
            kernel = s.get("kernel", {})
            result.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "path": s.get("path"),
                "type": s.get("type"),
                "kernel_id": kernel.get("id"),
                "kernel_state": kernel.get("execution_state"),
                "last_activity": kernel.get("last_activity"),
                "idle_seconds": format_idle_seconds(kernel.get("last_activity")),
                "idle_time": format_idle_time(kernel.get("last_activity")),
            })
        return result

    def shutdown_kernel(self, kernel_id: str) -> bool:
        """Shutdown a kernel."""
        return self._delete(f"api/kernels/{kernel_id}")

    def terminate_terminal(self, name: str) -> bool:
        """Terminate a terminal."""
        return self._delete(f"api/terminals/{name}")

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        return self._delete(f"api/sessions/{session_id}")

    def get_culler_status(self) -> dict | None:
        """Get culler status and settings from the extension."""
        try:
            return self._get("jupyterlab-kernel-terminal-workspace-culler-extension/status")
        except Exception:
            return None

    def get_terminals_connection(self) -> dict[str, bool]:
        """Get terminal connection status from the extension."""
        try:
            return self._get("jupyterlab-kernel-terminal-workspace-culler-extension/terminals-connection")
        except Exception:
            return {}


def cmd_list(client: JupyterClient, args: argparse.Namespace) -> int:
    """List all resources and their idle times."""
    kernels = client.list_kernels()
    terminals = client.list_terminals()
    sessions = client.list_sessions()
    culler_status = client.get_culler_status()
    terminals_connection = client.get_terminals_connection()

    # Add connection status to terminals
    for t in terminals:
        name = t.get("name")
        t["connected"] = terminals_connection.get(name, False)

    if args.json:
        output = {
            "kernels": kernels,
            "terminals": terminals,
            "sessions": sessions,
            "culler": culler_status,
        }
        print(json.dumps(output, indent=2, default=str))
        return 0

    # Human-readable output - Settings first
    print("CULLER SETTINGS")
    print("-" * 60)
    if culler_status:
        settings = culler_status.get("settings", {})
        running = culler_status.get("running", False)
        print(f"  Status: {'running' if running else 'stopped'}")
        print(f"  Check interval: {settings.get('cullCheckInterval', '?')} min")
        print(f"  Kernel culling: {'enabled' if settings.get('kernelCullEnabled') else 'disabled'}, timeout: {settings.get('kernelCullIdleTimeout', '?')} min")
        print(f"  Terminal culling: {'enabled' if settings.get('terminalCullEnabled') else 'disabled'}, timeout: {settings.get('terminalCullIdleTimeout', '?')} min, disconnected-only: {settings.get('terminalCullDisconnectedOnly', '?')}")
        print(f"  Session culling: {'enabled' if settings.get('sessionCullEnabled') else 'disabled'}, timeout: {settings.get('sessionCullIdleTimeout', '?')} min")
    else:
        print("  (culler extension not available)")

    print("\nKERNELS")
    print("-" * 60)
    if kernels:
        for k in kernels:
            state = k["execution_state"] or "unknown"
            print(f"  {k['id'][:8]}  {state:8}  idle: {k['idle_time']:>8}  ({k['name']})")
    else:
        print("  (none)")

    print("\nTERMINALS")
    print("-" * 60)
    if terminals:
        for t in terminals:
            conn_status = "connected" if t.get("connected") else "disconnected"
            print(f"  {t['name']:8}  {conn_status:12}  idle: {t['idle_time']:>8}")
    else:
        print("  (none)")

    print("\nSESSIONS")
    print("-" * 60)
    if sessions:
        for s in sessions:
            state = s["kernel_state"] or "unknown"
            path = s["path"] or "(no path)"
            if len(path) > 40:
                path = "..." + path[-37:]
            print(f"  {s['id'][:8]}  {state:8}  idle: {s['idle_time']:>8}  {path}")
    else:
        print("  (none)")

    return 0


def cmd_cull(client: JupyterClient, args: argparse.Namespace) -> int:
    """Cull idle resources."""
    kernels = client.list_kernels()
    terminals = client.list_terminals()
    sessions = client.list_sessions()

    # Default timeouts in seconds
    kernel_timeout = args.kernel_timeout * 60
    terminal_timeout = args.terminal_timeout * 60
    session_timeout = args.session_timeout * 60

    results = {
        "kernels_culled": [],
        "terminals_culled": [],
        "sessions_culled": [],
        "dry_run": args.dry_run,
    }

    # Cull idle kernels (skip busy ones)
    for k in kernels:
        if k["execution_state"] == "busy":
            continue
        if k["idle_seconds"] > 0 and k["idle_seconds"] > kernel_timeout:
            if args.dry_run:
                results["kernels_culled"].append({"id": k["id"], "idle_time": k["idle_time"], "action": "would_cull"})
            else:
                success = client.shutdown_kernel(k["id"])
                results["kernels_culled"].append({"id": k["id"], "idle_time": k["idle_time"], "action": "culled" if success else "failed"})

    # Cull idle terminals
    for t in terminals:
        if t["idle_seconds"] > 0 and t["idle_seconds"] > terminal_timeout:
            if args.dry_run:
                results["terminals_culled"].append({"name": t["name"], "idle_time": t["idle_time"], "action": "would_cull"})
            else:
                success = client.terminate_terminal(t["name"])
                results["terminals_culled"].append({"name": t["name"], "idle_time": t["idle_time"], "action": "culled" if success else "failed"})

    # Cull idle sessions
    for s in sessions:
        if s["kernel_state"] == "busy":
            continue
        if s["idle_seconds"] > 0 and s["idle_seconds"] > session_timeout:
            if args.dry_run:
                results["sessions_culled"].append({"id": s["id"], "idle_time": s["idle_time"], "action": "would_cull"})
            else:
                success = client.delete_session(s["id"])
                results["sessions_culled"].append({"id": s["id"], "idle_time": s["idle_time"], "action": "culled" if success else "failed"})

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    # Human-readable output
    prefix = "[DRY RUN] " if args.dry_run else ""

    if results["kernels_culled"]:
        print(f"{prefix}Kernels culled:")
        for k in results["kernels_culled"]:
            print(f"  {k['id'][:8]}  idle: {k['idle_time']}  ({k['action']})")
    else:
        print(f"{prefix}No kernels to cull")

    if results["terminals_culled"]:
        print(f"{prefix}Terminals culled:")
        for t in results["terminals_culled"]:
            print(f"  {t['name']}  idle: {t['idle_time']}  ({t['action']})")
    else:
        print(f"{prefix}No terminals to cull")

    if results["sessions_culled"]:
        print(f"{prefix}Sessions culled:")
        for s in results["sessions_culled"]:
            print(f"  {s['id'][:8]}  idle: {s['idle_time']}  ({s['action']})")
    else:
        print(f"{prefix}No sessions to cull")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        prog="jupyterlab_kernel_terminal_workspace_culler",
        description="List and cull idle Jupyter kernels, terminals, and sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  JUPYTER_SERVER_URL    Jupyter server URL (e.g., http://localhost:8888/)
  JUPYTER_TOKEN         Jupyter server authentication token

Examples:
  %(prog)s list                     List all resources and idle times
  %(prog)s list --json              List as JSON
  %(prog)s cull --dry-run           Show what would be culled
  %(prog)s cull                     Cull idle resources
  %(prog)s cull --kernel-timeout 30 Cull kernels idle > 30 minutes
""",
    )

    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--server-url", help="Jupyter server URL (overrides JUPYTER_SERVER_URL)")
    parser.add_argument("--token", help="Jupyter server token (overrides JUPYTER_TOKEN)")

    subparsers = parser.add_subparsers(dest="command", title="commands")

    # list command
    list_parser = subparsers.add_parser("list", help="List all resources and their idle times")
    list_parser.set_defaults(func=cmd_list)

    # cull command
    cull_parser = subparsers.add_parser("cull", help="Cull idle resources")
    cull_parser.add_argument("--dry-run", action="store_true", help="Simulate culling without actually terminating")
    cull_parser.add_argument("--kernel-timeout", type=int, default=60, metavar="MIN", help="Kernel idle timeout in minutes (default: 60)")
    cull_parser.add_argument("--terminal-timeout", type=int, default=60, metavar="MIN", help="Terminal idle timeout in minutes (default: 60)")
    cull_parser.add_argument("--session-timeout", type=int, default=10080, metavar="MIN", help="Session idle timeout in minutes (default: 10080)")
    cull_parser.set_defaults(func=cmd_cull)

    args = parser.parse_args(argv)

    # Show help if no command
    if not args.command:
        parser.print_help()
        return 0

    # Get server URL and token (auto-detect or from args)
    if args.server_url:
        server_url = args.server_url
        token = args.token  # Use provided token or None
    else:
        server_url, auto_token = get_jupyter_server_info()
        token = args.token if args.token else auto_token

    client = JupyterClient(server_url, token)

    try:
        return args.func(client, args)
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to Jupyter server at {server_url}", file=sys.stderr)
        return 1
    except requests.exceptions.HTTPError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
