"""Resource culler for idle kernels, terminals, and workspaces."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tornado.ioloop import PeriodicCallback

logger = logging.getLogger(__name__)


class ResourceCuller:
    """Culls idle kernels, terminals, and workspaces based on configurable timeouts."""

    def __init__(self, server_app: Any) -> None:
        self._server_app = server_app
        self._periodic_callback: PeriodicCallback | None = None

        # Default settings
        self._kernel_cull_enabled = True
        self._kernel_cull_idle_timeout = 60  # minutes (1 hour)
        self._terminal_cull_enabled = True
        self._terminal_cull_idle_timeout = 60  # minutes (1 hour)
        self._terminal_cull_disconnected_only = True  # only cull terminals with no active tab
        self._workspace_cull_enabled = True
        self._workspace_cull_idle_timeout = 10080  # minutes (7 days)
        self._cull_check_interval = 5  # minutes

        # Last culling result for notification polling
        self._last_cull_result: dict[str, list[str]] = {
            "kernels_culled": [],
            "terminals_culled": [],
            "workspaces_culled": [],
        }
        self._result_consumed = True  # Track if frontend has fetched the result

        # Active terminals reported by frontend (terminals with open tabs)
        self._active_terminals: set[str] = set()

        # Workspace manager (lazy initialization)
        self._workspace_manager: Any = None

    @property
    def kernel_manager(self) -> Any:
        """Access the kernel manager from jupyter_server."""
        return self._server_app.kernel_manager

    @property
    def terminal_manager(self) -> Any:
        """Access the terminal manager from jupyter_server."""
        # Terminal manager may be on server_app or in web_app settings
        if hasattr(self._server_app, "terminal_manager"):
            return self._server_app.terminal_manager
        return self._server_app.web_app.settings.get("terminal_manager")

    @property
    def workspace_manager(self) -> Any:
        """Access the workspace manager from jupyterlab_server."""
        if self._workspace_manager is None:
            try:
                from jupyterlab_server.workspaces_handler import WorkspacesManager

                # Get workspaces directory from jupyterlab settings
                workspaces_dir = Path.home() / ".jupyter" / "lab" / "workspaces"
                if workspaces_dir.exists():
                    self._workspace_manager = WorkspacesManager(str(workspaces_dir))
                else:
                    logger.warning(
                        f"[Culler] Workspaces directory not found: {workspaces_dir}"
                    )
            except ImportError:
                logger.warning(
                    "[Culler] jupyterlab_server not available for workspace management"
                )
        return self._workspace_manager

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Update culler settings from frontend (camelCase -> snake_case)."""
        if "kernelCullEnabled" in settings:
            self._kernel_cull_enabled = settings["kernelCullEnabled"]
        if "kernelCullIdleTimeout" in settings:
            self._kernel_cull_idle_timeout = settings["kernelCullIdleTimeout"]
        if "terminalCullEnabled" in settings:
            self._terminal_cull_enabled = settings["terminalCullEnabled"]
        if "terminalCullIdleTimeout" in settings:
            self._terminal_cull_idle_timeout = settings["terminalCullIdleTimeout"]
        if "terminalCullDisconnectedOnly" in settings:
            self._terminal_cull_disconnected_only = settings["terminalCullDisconnectedOnly"]
        if "workspaceCullEnabled" in settings:
            self._workspace_cull_enabled = settings["workspaceCullEnabled"]
        if "workspaceCullIdleTimeout" in settings:
            self._workspace_cull_idle_timeout = settings["workspaceCullIdleTimeout"]
        if "cullCheckInterval" in settings:
            new_interval = settings["cullCheckInterval"]
            if new_interval != self._cull_check_interval:
                self._cull_check_interval = new_interval
                # Restart periodic callback with new interval
                if self._periodic_callback is not None:
                    self.stop()
                    self.start()

        logger.info(
            f"[Culler] Settings updated: kernel={self._kernel_cull_enabled}/{self._kernel_cull_idle_timeout}min, "
            f"terminal={self._terminal_cull_enabled}/{self._terminal_cull_idle_timeout}min"
            f"(disconnected_only={self._terminal_cull_disconnected_only}), "
            f"workspace={self._workspace_cull_enabled}/{self._workspace_cull_idle_timeout}min, "
            f"interval={self._cull_check_interval}min"
        )

    def get_settings(self) -> dict[str, Any]:
        """Return current settings."""
        return {
            "kernelCullEnabled": self._kernel_cull_enabled,
            "kernelCullIdleTimeout": self._kernel_cull_idle_timeout,
            "terminalCullEnabled": self._terminal_cull_enabled,
            "terminalCullIdleTimeout": self._terminal_cull_idle_timeout,
            "terminalCullDisconnectedOnly": self._terminal_cull_disconnected_only,
            "workspaceCullEnabled": self._workspace_cull_enabled,
            "workspaceCullIdleTimeout": self._workspace_cull_idle_timeout,
            "cullCheckInterval": self._cull_check_interval,
        }

    def get_status(self) -> dict[str, Any]:
        """Return culler status including settings and running state."""
        return {
            "running": self._periodic_callback is not None,
            "settings": self.get_settings(),
        }

    def start(self) -> None:
        """Start the periodic culling task."""
        if self._periodic_callback is not None:
            logger.warning("[Culler] Already running, ignoring start request")
            return

        interval_ms = self._cull_check_interval * 60 * 1000
        self._periodic_callback = PeriodicCallback(
            self._cull_idle_resources, interval_ms
        )
        self._periodic_callback.start()
        logger.info(
            f"[Culler] Started with check interval of {self._cull_check_interval} minutes"
        )

    def stop(self) -> None:
        """Stop the periodic culling task."""
        if self._periodic_callback is not None:
            self._periodic_callback.stop()
            self._periodic_callback = None
            logger.info("[Culler] Stopped")

    def get_last_cull_result(self) -> dict[str, list[str]]:
        """Return last culling result and mark as consumed."""
        if self._result_consumed:
            return {"kernels_culled": [], "terminals_culled": [], "workspaces_culled": []}
        self._result_consumed = True
        return self._last_cull_result

    def get_terminals_connection_status(self) -> dict[str, bool]:
        """Return connection status (has active tab) for all terminals."""
        result: dict[str, bool] = {}
        terminal_mgr = self.terminal_manager
        if terminal_mgr is None:
            return result

        try:
            terminals = terminal_mgr.list()
            for terminal in terminals:
                name = terminal.get("name")
                if name:
                    result[name] = self._terminal_has_active_tab(name)
        except Exception:
            pass

        return result

    def set_active_terminals(self, terminals: list[str]) -> None:
        """Update the set of terminals that have open tabs in the frontend."""
        self._active_terminals = set(terminals)
        logger.debug(f"[Culler] Active terminals updated: {self._active_terminals}")

    def _terminal_has_active_tab(self, name: str) -> bool:
        """Check if a terminal has an active tab in the frontend."""
        return name in self._active_terminals

    def list_workspaces(self) -> list[dict[str, Any]]:
        """Return list of workspaces with their metadata."""
        result: list[dict[str, Any]] = []
        ws_mgr = self.workspace_manager
        if ws_mgr is None:
            return result

        try:
            for ws in ws_mgr.list_workspaces():
                metadata = ws.get("metadata", {})
                result.append({
                    "id": metadata.get("id", "unknown"),
                    "last_modified": metadata.get("last_modified"),
                    "created": metadata.get("created"),
                })
        except Exception as e:
            logger.error(f"[Culler] Failed to list workspaces: {e}")

        return result

    async def _cull_idle_resources(self) -> None:
        """Main culling routine called by periodic callback."""
        kernels_culled: list[str] = []
        terminals_culled: list[str] = []
        workspaces_culled: list[str] = []

        if self._kernel_cull_enabled:
            kernels_culled = await self._cull_kernels()

        if self._terminal_cull_enabled:
            terminals_culled = await self._cull_terminals()

        if self._workspace_cull_enabled:
            workspaces_culled = self._cull_workspaces()

        # Store result for notification polling
        if kernels_culled or terminals_culled or workspaces_culled:
            self._last_cull_result = {
                "kernels_culled": kernels_culled,
                "terminals_culled": terminals_culled,
                "workspaces_culled": workspaces_culled,
            }
            self._result_consumed = False

    async def _cull_kernels(self) -> list[str]:
        """Cull idle kernels exceeding timeout threshold."""
        culled: list[str] = []
        now = datetime.now(timezone.utc)
        timeout_seconds = self._kernel_cull_idle_timeout * 60

        try:
            kernel_ids = list(self.kernel_manager.list_kernel_ids())
        except Exception as e:
            logger.error(f"[Culler] Failed to list kernels: {e}")
            return culled

        for kernel_id in kernel_ids:
            try:
                kernel = self.kernel_manager.get_kernel(kernel_id)
                if kernel is None:
                    continue

                # Check execution state - skip busy kernels
                execution_state = getattr(kernel, "execution_state", "idle")
                if execution_state == "busy":
                    continue

                # Check last activity
                last_activity = getattr(kernel, "last_activity", None)
                if last_activity is None:
                    continue

                # Ensure timezone-aware comparison
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=timezone.utc)

                idle_seconds = (now - last_activity).total_seconds()
                idle_minutes = idle_seconds / 60

                if idle_seconds > timeout_seconds:
                    logger.info(
                        f"[Culler] CULLING KERNEL {kernel_id} - idle {idle_minutes:.1f} minutes "
                        f"(threshold: {self._kernel_cull_idle_timeout})"
                    )
                    await self.kernel_manager.shutdown_kernel(kernel_id)
                    logger.info(f"[Culler] Kernel {kernel_id} culled successfully")
                    culled.append(kernel_id)

            except Exception as e:
                logger.error(f"[Culler] Failed to cull kernel {kernel_id}: {e}")

        return culled

    async def _cull_terminals(self) -> list[str]:
        """Cull idle terminals exceeding timeout threshold."""
        culled: list[str] = []
        now = datetime.now(timezone.utc)
        timeout_seconds = self._terminal_cull_idle_timeout * 60

        terminal_mgr = self.terminal_manager
        if terminal_mgr is None:
            logger.warning("[Culler] Terminal manager not available")
            return culled

        try:
            terminals = terminal_mgr.list()
        except Exception as e:
            logger.error(f"[Culler] Failed to list terminals: {e}")
            return culled

        for terminal in terminals:
            try:
                name = terminal.get("name")
                if name is None:
                    continue

                # Check for active tabs if setting enabled
                if self._terminal_cull_disconnected_only:
                    if self._terminal_has_active_tab(name):
                        logger.debug(
                            f"[Culler] Skipping terminal {name} - has active tab"
                        )
                        continue

                last_activity = terminal.get("last_activity")
                if last_activity is None:
                    continue

                # Parse datetime if string
                if isinstance(last_activity, str):
                    last_activity = datetime.fromisoformat(
                        last_activity.replace("Z", "+00:00")
                    )

                # Ensure timezone-aware comparison
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=timezone.utc)

                idle_seconds = (now - last_activity).total_seconds()
                idle_minutes = idle_seconds / 60

                if idle_seconds > timeout_seconds:
                    logger.info(
                        f"[Culler] CULLING TERMINAL {name} - idle {idle_minutes:.1f} minutes "
                        f"(threshold: {self._terminal_cull_idle_timeout})"
                    )
                    await terminal_mgr.terminate(name)
                    logger.info(f"[Culler] Terminal {name} culled successfully")
                    culled.append(name)

            except Exception as e:
                logger.error(f"[Culler] Failed to cull terminal {name}: {e}")

        return culled

    def _cull_workspaces(self) -> list[str]:
        """Cull idle workspaces exceeding timeout threshold."""
        culled: list[str] = []
        now = datetime.now(timezone.utc)
        timeout_seconds = self._workspace_cull_idle_timeout * 60

        ws_mgr = self.workspace_manager
        if ws_mgr is None:
            logger.warning("[Culler] Workspace manager not available")
            return culled

        try:
            workspaces = list(ws_mgr.list_workspaces())
        except Exception as e:
            logger.error(f"[Culler] Failed to list workspaces: {e}")
            return culled

        for workspace in workspaces:
            try:
                metadata = workspace.get("metadata", {})
                workspace_id = metadata.get("id")
                if workspace_id is None:
                    continue

                # Never cull the default workspace
                if workspace_id == "default":
                    logger.debug("[Culler] Skipping default workspace")
                    continue

                last_modified = metadata.get("last_modified")
                if last_modified is None:
                    continue

                # Parse datetime if string
                if isinstance(last_modified, str):
                    last_modified = datetime.fromisoformat(
                        last_modified.replace("Z", "+00:00")
                    )

                # Ensure timezone-aware comparison
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)

                idle_seconds = (now - last_modified).total_seconds()
                idle_minutes = idle_seconds / 60

                if idle_seconds > timeout_seconds:
                    logger.info(
                        f"[Culler] CULLING WORKSPACE {workspace_id} - idle {idle_minutes:.1f} minutes "
                        f"(threshold: {self._workspace_cull_idle_timeout})"
                    )
                    ws_mgr.delete(workspace_id)
                    logger.info(f"[Culler] Workspace {workspace_id} culled successfully")
                    culled.append(workspace_id)

            except Exception as e:
                logger.error(f"[Culler] Failed to cull workspace {workspace_id}: {e}")

        return culled

    def cull_workspaces_with_timeout(
        self, timeout_minutes: int, dry_run: bool = False
    ) -> list[dict[str, Any]]:
        """Cull workspaces with specified timeout (for CLI use).

        Args:
            timeout_minutes: Idle timeout in minutes
            dry_run: If True, return what would be culled without actually culling

        Returns:
            List of workspace dicts with id, idle_time, and action
        """
        result: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        timeout_seconds = timeout_minutes * 60

        ws_mgr = self.workspace_manager
        if ws_mgr is None:
            logger.warning("[Culler] Workspace manager not available")
            return result

        try:
            workspaces = list(ws_mgr.list_workspaces())
        except Exception as e:
            logger.error(f"[Culler] Failed to list workspaces: {e}")
            return result

        for workspace in workspaces:
            try:
                metadata = workspace.get("metadata", {})
                workspace_id = metadata.get("id")
                if workspace_id is None:
                    continue

                # Never cull the default workspace
                if workspace_id == "default":
                    continue

                last_modified = metadata.get("last_modified")
                if last_modified is None:
                    continue

                # Parse datetime if string
                if isinstance(last_modified, str):
                    last_modified = datetime.fromisoformat(
                        last_modified.replace("Z", "+00:00")
                    )

                # Ensure timezone-aware comparison
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)

                idle_seconds = (now - last_modified).total_seconds()
                idle_minutes = idle_seconds / 60

                if idle_seconds > timeout_seconds:
                    if dry_run:
                        # Format idle time for display
                        if idle_seconds < 3600:
                            idle_time = f"{idle_minutes:.1f}m"
                        elif idle_seconds < 86400:
                            idle_time = f"{idle_seconds / 3600:.1f}h"
                        else:
                            idle_time = f"{idle_seconds / 86400:.1f}d"
                        result.append({
                            "id": workspace_id,
                            "idle_time": idle_time,
                            "action": "would_cull",
                        })
                    else:
                        logger.info(
                            f"[Culler] CLI CULLING WORKSPACE {workspace_id} - "
                            f"idle {idle_minutes:.1f} minutes (threshold: {timeout_minutes})"
                        )
                        ws_mgr.delete(workspace_id)
                        logger.info(f"[Culler] Workspace {workspace_id} culled successfully")
                        # Format idle time for display
                        if idle_seconds < 3600:
                            idle_time = f"{idle_minutes:.1f}m"
                        elif idle_seconds < 86400:
                            idle_time = f"{idle_seconds / 3600:.1f}h"
                        else:
                            idle_time = f"{idle_seconds / 86400:.1f}d"
                        result.append({
                            "id": workspace_id,
                            "idle_time": idle_time,
                            "action": "culled",
                        })

            except Exception as e:
                logger.error(f"[Culler] Failed to cull workspace {workspace_id}: {e}")
                result.append({
                    "id": workspace_id,
                    "idle_time": "unknown",
                    "action": "failed",
                })

        return result
