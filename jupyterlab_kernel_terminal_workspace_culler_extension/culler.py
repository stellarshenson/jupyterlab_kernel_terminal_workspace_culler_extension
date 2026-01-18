"""Resource culler for idle kernels, terminals, and sessions."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from tornado.ioloop import PeriodicCallback

logger = logging.getLogger(__name__)


class ResourceCuller:
    """Culls idle kernels, terminals, and sessions based on configurable timeouts."""

    def __init__(self, server_app: Any) -> None:
        self._server_app = server_app
        self._periodic_callback: PeriodicCallback | None = None

        # Default settings
        self._kernel_cull_enabled = True
        self._kernel_cull_idle_timeout = 60  # minutes (1 hour)
        self._terminal_cull_enabled = True
        self._terminal_cull_idle_timeout = 60  # minutes (1 hour)
        self._terminal_cull_disconnected_only = True  # only cull terminals with no active tab
        self._session_cull_enabled = False
        self._session_cull_idle_timeout = 10080  # minutes (7 days)
        self._cull_check_interval = 5  # minutes

        # Last culling result for notification polling
        self._last_cull_result: dict[str, list[str]] = {
            "kernels_culled": [],
            "terminals_culled": [],
            "sessions_culled": [],
        }
        self._result_consumed = True  # Track if frontend has fetched the result

        # Active terminals reported by frontend (terminals with open tabs)
        self._active_terminals: set[str] = set()

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
    def session_manager(self) -> Any:
        """Access the session manager from jupyter_server."""
        return self._server_app.session_manager

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
        if "sessionCullEnabled" in settings:
            self._session_cull_enabled = settings["sessionCullEnabled"]
        if "sessionCullIdleTimeout" in settings:
            self._session_cull_idle_timeout = settings["sessionCullIdleTimeout"]
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
            f"session={self._session_cull_enabled}/{self._session_cull_idle_timeout}min, "
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
            "sessionCullEnabled": self._session_cull_enabled,
            "sessionCullIdleTimeout": self._session_cull_idle_timeout,
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
            return {"kernels_culled": [], "terminals_culled": [], "sessions_culled": []}
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

    async def _cull_idle_resources(self) -> None:
        """Main culling routine called by periodic callback."""
        kernels_culled: list[str] = []
        terminals_culled: list[str] = []
        sessions_culled: list[str] = []

        if self._kernel_cull_enabled:
            kernels_culled = await self._cull_kernels()

        if self._terminal_cull_enabled:
            terminals_culled = await self._cull_terminals()

        if self._session_cull_enabled:
            sessions_culled = await self._cull_sessions()

        # Store result for notification polling
        if kernels_culled or terminals_culled or sessions_culled:
            self._last_cull_result = {
                "kernels_culled": kernels_culled,
                "terminals_culled": terminals_culled,
                "sessions_culled": sessions_culled,
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

    async def _cull_sessions(self) -> list[str]:
        """Cull idle sessions exceeding timeout threshold."""
        culled: list[str] = []
        now = datetime.now(timezone.utc)
        timeout_seconds = self._session_cull_idle_timeout * 60

        try:
            sessions = await self.session_manager.list_sessions()
        except Exception as e:
            logger.error(f"[Culler] Failed to list sessions: {e}")
            return culled

        for session in sessions:
            try:
                session_id = session.get("id")
                if session_id is None:
                    continue

                # Get kernel info from session
                kernel_info = session.get("kernel", {})
                kernel_id = kernel_info.get("id")

                if kernel_id:
                    # Check kernel last activity
                    try:
                        kernel = self.kernel_manager.get_kernel(kernel_id)
                        if kernel is None:
                            continue

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
                                f"[Culler] CULLING SESSION {session_id} - idle {idle_minutes:.1f} minutes "
                                f"(threshold: {self._session_cull_idle_timeout})"
                            )
                            await self.session_manager.delete_session(session_id)
                            logger.info(
                                f"[Culler] Session {session_id} culled successfully"
                            )
                            culled.append(session_id)

                    except Exception as e:
                        logger.error(
                            f"[Culler] Failed to get kernel for session {session_id}: {e}"
                        )

            except Exception as e:
                logger.error(f"[Culler] Failed to cull session {session_id}: {e}")

        return culled
