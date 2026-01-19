"""Route handlers for the resource culler extension."""

import json
from typing import TYPE_CHECKING

import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

if TYPE_CHECKING:
    from .culler import ResourceCuller

# Global reference to culler instance - set by __init__.py
_culler: "ResourceCuller | None" = None


def set_culler(culler: "ResourceCuller") -> None:
    """Set the global culler instance."""
    global _culler
    _culler = culler


def get_culler() -> "ResourceCuller | None":
    """Get the global culler instance."""
    return _culler


class SettingsHandler(APIHandler):
    """Handler for updating culler settings."""

    @tornado.web.authenticated
    def post(self) -> None:
        """Update culler settings from frontend."""
        if _culler is None:
            self.set_status(503)
            self.finish(json.dumps({"error": "Culler not initialized"}))
            return

        try:
            settings = json.loads(self.request.body)
            _culler.update_settings(settings)
            self.finish(json.dumps({"status": "ok"}))
        except json.JSONDecodeError:
            self.set_status(400)
            self.finish(json.dumps({"error": "Invalid JSON"}))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": str(e)}))


class StatusHandler(APIHandler):
    """Handler for returning culler status."""

    @tornado.web.authenticated
    def get(self) -> None:
        """Return culler status and settings."""
        if _culler is None:
            self.set_status(503)
            self.finish(json.dumps({"error": "Culler not initialized"}))
            return

        self.finish(json.dumps(_culler.get_status()))


class CullResultHandler(APIHandler):
    """Handler for returning last culling summary."""

    @tornado.web.authenticated
    def get(self) -> None:
        """Return last culling result for notification polling."""
        if _culler is None:
            self.finish(
                json.dumps(
                    {
                        "kernels_culled": [],
                        "terminals_culled": [],
                        "workspaces_culled": [],
                    }
                )
            )
            return

        self.finish(json.dumps(_culler.get_last_cull_result()))


class TerminalsConnectionHandler(APIHandler):
    """Handler for returning terminal connection status."""

    @tornado.web.authenticated
    def get(self) -> None:
        """Return connection status for all terminals."""
        if _culler is None:
            self.finish(json.dumps({}))
            return

        self.finish(json.dumps(_culler.get_terminals_connection_status()))


class ActiveTerminalsHandler(APIHandler):
    """Handler for receiving active terminal list from frontend."""

    @tornado.web.authenticated
    def post(self) -> None:
        """Update active terminals list."""
        if _culler is None:
            self.set_status(503)
            self.finish(json.dumps({"error": "Culler not initialized"}))
            return
        try:
            data = json.loads(self.request.body)
            terminals = data.get("terminals", [])
            _culler.set_active_terminals(terminals)
            self.finish(json.dumps({"status": "ok"}))
        except json.JSONDecodeError:
            self.set_status(400)
            self.finish(json.dumps({"error": "Invalid JSON"}))
        except Exception as e:
            self.set_status(500)
            self.finish(json.dumps({"error": str(e)}))


class WorkspacesHandler(APIHandler):
    """Handler for listing workspaces."""

    @tornado.web.authenticated
    def get(self) -> None:
        """Return list of workspaces with metadata."""
        if _culler is None:
            self.finish(json.dumps([]))
            return

        self.finish(json.dumps(_culler.list_workspaces()))


def setup_route_handlers(web_app: tornado.web.Application) -> None:
    """Set up route handlers for the extension."""
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    namespace = "jupyterlab-kernel-terminal-workspace-culler-extension"

    handlers = [
        (url_path_join(base_url, namespace, "settings"), SettingsHandler),
        (url_path_join(base_url, namespace, "status"), StatusHandler),
        (url_path_join(base_url, namespace, "cull-result"), CullResultHandler),
        (url_path_join(base_url, namespace, "terminals-connection"), TerminalsConnectionHandler),
        (url_path_join(base_url, namespace, "active-terminals"), ActiveTerminalsHandler),
        (url_path_join(base_url, namespace, "workspaces"), WorkspacesHandler),
    ]

    web_app.add_handlers(host_pattern, handlers)
