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

        # Active terminals reported by frontend, keyed by client id ->
        # (names, last report time, client report interval in minutes).
        # Kept per-client and unioned so one client's report cannot clobber another's
        # (a terminal open in any client is protected); stale clients expire (see TTL below).
        self._active_terminals_by_client: dict[str, tuple[set[str], datetime, int]] = {}

        # When each terminal last had evidence of an open tab (websocket client or
        # fresh report). A terminal whose tab closes or disconnects gets a fresh
        # idle-timeout grace from that moment, so a transient websocket loss
        # (network blip, sleep/wake) cannot cull it on the next check.
        self._terminal_tab_last_seen: dict[str, datetime] = {}

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

    def _resolve_workspaces_dir(self) -> Path:
        """Resolve the workspaces directory the running server actually uses.

        Prefers the ``workspaces_dir`` trait of the loaded lab extension app
        (set via ``--LabApp.workspaces_dir`` or config files); falls back to
        JupyterLab's own resolver, which honours ``JUPYTERLAB_WORKSPACES_DIR``
        before defaulting to ``<config dir>/lab/workspaces``. Culling a
        directory the live server does not use would either no-op silently or
        delete workspace files belonging to another deployment.
        """
        ext_mgr = getattr(self._server_app, "extension_manager", None)
        if ext_mgr is not None:
            for apps in getattr(ext_mgr, "extension_apps", {}).values():
                for app in apps:
                    ws_dir = getattr(app, "workspaces_dir", "")
                    if ws_dir:
                        return Path(ws_dir)
        try:
            from jupyterlab.commands import get_workspaces_dir

            return Path(get_workspaces_dir())
        except ImportError:
            from jupyter_core.paths import jupyter_config_dir

            return Path(jupyter_config_dir()) / "lab" / "workspaces"

    @property
    def workspace_manager(self) -> Any:
        """Access the workspace manager from jupyterlab_server."""
        if self._workspace_manager is None:
            try:
                from jupyterlab_server.workspaces_handler import WorkspacesManager

                workspaces_dir = self._resolve_workspaces_dir()
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

    # REST-settable settings: camelCase key -> (attribute, expected type)
    _SETTING_SPEC = {
        "kernelCullEnabled": ("_kernel_cull_enabled", bool),
        "kernelCullIdleTimeout": ("_kernel_cull_idle_timeout", int),
        "terminalCullEnabled": ("_terminal_cull_enabled", bool),
        "terminalCullIdleTimeout": ("_terminal_cull_idle_timeout", int),
        "terminalCullDisconnectedOnly": ("_terminal_cull_disconnected_only", bool),
        "workspaceCullEnabled": ("_workspace_cull_enabled", bool),
        "workspaceCullIdleTimeout": ("_workspace_cull_idle_timeout", int),
        "cullCheckInterval": ("_cull_check_interval", int),
    }

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Update culler settings from frontend (camelCase -> snake_case).

        Every provided value is validated before any state mutates, so a bad
        payload cannot half-apply; raises ValueError on a type mismatch.
        Integer values (minutes) are clamped to a minimum of 1.
        """
        validated: dict[str, Any] = {}
        for key, (attr, expected) in self._SETTING_SPEC.items():
            if key not in settings:
                continue
            value = settings[key]
            # exact type: bool is an int subclass, so isinstance would let
            # true/false through as integers (and vice versa)
            if type(value) is not expected:
                kind = "a boolean" if expected is bool else "an integer"
                raise ValueError(f"{key} must be {kind}")
            validated[attr] = max(1, value) if expected is int else value

        old_interval = self._cull_check_interval
        for attr, value in validated.items():
            setattr(self, attr, value)

        if self._cull_check_interval != old_interval and self._periodic_callback is not None:
            # Restart periodic callback with new interval
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
        """Return protection status for all terminals.

        True when a terminal has an open tab OR is referenced by an existing
        workspace (both protect it from culling); also True when workspace
        references cannot be verified, so CLI consumers fail safe too.
        """
        result: dict[str, bool] = {}
        terminal_mgr = self.terminal_manager
        if terminal_mgr is None:
            return result

        ws_referenced = self._workspace_referenced_terminals()
        try:
            terminals = terminal_mgr.list()
            for terminal in terminals:
                name = terminal.get("name")
                if name:
                    result[name] = (
                        self._terminal_has_active_tab(name)
                        or ws_referenced is None
                        or name in ws_referenced
                    )
        except Exception:
            pass

        return result

    # A live frontend re-reports every check interval; drop a client silent for
    # this many intervals so a closed browser stops protecting its terminals.
    # 3 (not 2) leaves a full interval of grace for a single dropped report.
    _ACTIVE_TERMINAL_STALE_INTERVALS = 3

    def set_active_terminals(
        self,
        terminals: list[str],
        client_id: str = "default",
        interval_minutes: int | None = None,
    ) -> None:
        """Record the terminals a given frontend client currently has open.

        ``interval_minutes`` is the client's own report cadence; staleness is
        judged against it rather than the server interval, so a client that has
        not yet picked up an interval change is not wrongly expired.
        """
        if type(interval_minutes) is not int or interval_minutes < 1:
            interval_minutes = self._cull_check_interval
        now = datetime.now(timezone.utc)
        self._active_terminals_by_client[client_id] = (
            set(terminals),
            now,
            interval_minutes,
        )
        # Prune on every write so the map stays bounded even when no culling
        # path (which would otherwise prune) ever runs
        self._prune_stale_clients(now)
        logger.debug(f"[Culler] Active terminals for client {client_id}: {terminals}")

    def _prune_stale_clients(self, now: datetime) -> None:
        """Drop clients silent beyond their own report-interval TTL."""
        stale = [
            client_id
            for client_id, (_names, reported_at, interval) in self._active_terminals_by_client.items()
            if (now - reported_at).total_seconds()
            > interval * self._ACTIVE_TERMINAL_STALE_INTERVALS * 60
        ]
        for client_id in stale:
            del self._active_terminals_by_client[client_id]

    def _active_terminal_names(self) -> set[str]:
        """Union of terminals reported open by any client with a recent report.

        Entries from clients silent for more than ``_ACTIVE_TERMINAL_STALE_INTERVALS``
        of their own report intervals are pruned, so a closed browser tab no longer
        protects its terminals from culling.
        """
        self._prune_stale_clients(datetime.now(timezone.utc))
        active: set[str] = set()
        for names, _reported_at, _interval in self._active_terminals_by_client.values():
            active |= names
        return active

    def _terminal_has_ws_client(self, name: str) -> bool:
        """True when at least one websocket client is attached to the terminal.

        An open terminal tab holds an open websocket to its terminal (terminado
        registers every connection in ``PtyWithClients.clients``), so this is
        ground truth the server observes directly. Frontend reports alone are
        not enough: browsers throttle or freeze timers in background tabs, so a
        client with an open tab can go silent past the report TTL and its
        terminal would lose protection despite the tab being open.
        """
        terminals = getattr(self.terminal_manager, "terminals", None)
        if not isinstance(terminals, dict):
            # Non-terminado manager without a per-pty registry; fall back to reports
            return False
        pty = terminals.get(name)
        return bool(pty is not None and getattr(pty, "clients", None))

    def _terminal_has_active_tab(self, name: str) -> bool:
        """Check if a terminal has an open tab: a live websocket client
        (ground truth) or a recent frontend report naming it."""
        return self._terminal_has_ws_client(name) or name in self._active_terminal_names()

    def _workspace_referenced_terminals(self) -> set[str] | None:
        """Terminal names referenced by any existing workspace's layout.

        A terminal open in a workspace that has not been culled must never be
        culled itself. Culling the workspace first releases its terminals -
        unless another not-yet-culled workspace still references them (the
        cascade). Workspace layouts store terminals as ``terminal:<name>``
        keys in their ``data`` section.

        Returns None when workspaces exist but cannot be listed (caller must
        fail safe and skip terminal culling), and an empty set when there is
        no workspace manager at all (no workspace concept, e.g. bare
        jupyter_server).
        """
        ws_mgr = self.workspace_manager
        if ws_mgr is None:
            return set()
        try:
            referenced: set[str] = set()
            for ws in ws_mgr.list_workspaces():
                for key in ws.get("data", {}):
                    if key.startswith("terminal:"):
                        referenced.add(key.split(":", 1)[1])
            return referenced
        except Exception as e:
            logger.error(
                f"[Culler] Failed to list workspace terminal references: {e}"
            )
            return None

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

        # Workspaces before terminals: a culled workspace releases the
        # terminals it referenced, so the cascade lands in the same pass
        if self._workspace_cull_enabled:
            workspaces_culled = self._cull_workspaces()

        if self._terminal_cull_enabled:
            terminals_culled = await self._cull_terminals()

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

        # Terminals open in any not-yet-culled workspace are NEVER culled;
        # the workspace must be culled first, which releases them (cascade).
        # None means workspaces exist but could not be read - fail safe and
        # cull nothing rather than kill a possibly-referenced terminal.
        ws_referenced = self._workspace_referenced_terminals()
        if ws_referenced is None:
            logger.warning(
                "[Culler] Cannot verify workspace terminal references; "
                "skipping terminal culling this pass"
            )
            return culled

        # Forget tab history for terminals that no longer exist
        current_names = {t.get("name") for t in terminals}
        for gone in set(self._terminal_tab_last_seen) - current_names:
            del self._terminal_tab_last_seen[gone]

        for terminal in terminals:
            try:
                name = terminal.get("name")
                if name is None:
                    continue

                # Tab check FIRST (when the setting gates on it): an open-tab
                # terminal is virtually always also workspace-referenced, and
                # skipping on the reference alone would never stamp the grace
                # anchor - the terminal would then be culled within one check
                # interval of its reference disappearing (tab closed, workspace
                # culled) instead of getting the documented full-timeout grace
                if self._terminal_cull_disconnected_only:
                    if self._terminal_has_active_tab(name):
                        self._terminal_tab_last_seen[name] = now
                        logger.debug(
                            f"[Culler] Skipping terminal {name} - has active tab"
                        )
                        continue

                if name in ws_referenced:
                    logger.debug(
                        f"[Culler] Skipping terminal {name} - open in a workspace"
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

                # A terminal whose tab closed or disconnected becomes eligible one
                # full idle timeout after that moment (the documented semantics),
                # so a transient websocket loss - network blip, exhausted frontend
                # reconnect attempts, sleep/wake - cannot cull it on the next check
                if self._terminal_cull_disconnected_only:
                    tab_last_seen = self._terminal_tab_last_seen.get(name)
                    if tab_last_seen is not None and tab_last_seen > last_activity:
                        last_activity = tab_last_seen

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

    @staticmethod
    def _is_cullable_workspace(workspace_id: str) -> bool:
        """Only auto-generated workspaces (auto-0, auto-k, ...) are cull-eligible.

        Named workspaces and the default/primary layout are always protected. A
        leading slash (some clients store the id as ``/auto-0``) is normalized.
        """
        return workspace_id.lstrip("/").startswith("auto-")

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

                # Only auto-generated workspaces are eligible; named and default layouts are protected
                if not self._is_cullable_workspace(workspace_id):
                    logger.debug(f"[Culler] Skipping protected workspace {workspace_id}")
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

                # Only auto-generated workspaces are eligible; named and default layouts are protected
                if not self._is_cullable_workspace(workspace_id):
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
