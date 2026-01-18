# jupyterlab_kernel_terminal_workspace_culler_extension

[![GitHub Actions](https://github.com/stellarshenson/jupyterlab_kernel_terminal_workspace_culler_extension/actions/workflows/build.yml/badge.svg)](https://github.com/stellarshenson/jupyterlab_kernel_terminal_workspace_culler_extension/actions/workflows/build.yml)
[![npm version](https://img.shields.io/npm/v/jupyterlab_kernel_terminal_workspace_culler_extension.svg)](https://www.npmjs.com/package/jupyterlab_kernel_terminal_workspace_culler_extension)
[![PyPI version](https://img.shields.io/pypi/v/jupyterlab-kernel-terminal-workspace-culler-extension.svg)](https://pypi.org/project/jupyterlab-kernel-terminal-workspace-culler-extension/)
[![Total PyPI downloads](https://static.pepy.tech/badge/jupyterlab-kernel-terminal-workspace-culler-extension)](https://pepy.tech/project/jupyterlab-kernel-terminal-workspace-culler-extension)
[![JupyterLab 4](https://img.shields.io/badge/JupyterLab-4-orange.svg)](https://jupyterlab.readthedocs.io/en/stable/)
[![Brought To You By KOLOMOLO](https://img.shields.io/badge/Brought%20To%20You%20By-KOLOMOLO-00ffff?style=flat)](https://kolomolo.com)
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-blue?style=flat)](https://www.paypal.com/donate/?hosted_button_id=B4KPBJDLLXTSA)

Automatically cull idle kernels, terminals, and sessions after configurable timeout periods. Helps manage system resources by cleaning up unused sessions that accumulate during long JupyterLab usage.

## Features

- **Idle kernel culling** - Shut down kernels idle beyond timeout (checks `execution_state` and `last_activity`)
- **Idle terminal culling** - Close terminals with no WebSocket activity beyond timeout
- **Session culling** - Remove stale sessions based on associated kernel activity
- **Configurable timeouts** - All timeouts adjustable via JupyterLab Settings
- **Notifications** - Optional toast notifications when resources are culled (requires `jupyterlab-notifications`)
- **Server-side detection** - Uses tornado PeriodicCallback for accurate activity tracking

## Default Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Kernel timeout | 60 min (1 hour) | Idle kernels culled after this period |
| Terminal timeout | 60 min (1 hour) | Inactive terminals culled after this period |
| Disconnected only | enabled | Only cull terminals with no open browser tab |
| Session timeout | 10080 min (7 days) | Idle sessions culled after this period |
| Check interval | 5 min | How often the culler checks for idle resources |
| Notifications | enabled | Show notification when resources are culled |

## How Idle Detection Works

**Kernels**: Checked for `execution_state` (busy kernels are never culled) and `last_activity` timestamp. A kernel is idle when it's not executing and hasn't had activity beyond the timeout.

**Terminals**: By default, only terminals with no active browser tab are culled (controlled by "Only Cull Disconnected Terminals" setting). When a terminal tab is open, it maintains a WebSocket connection and won't be culled regardless of idle time. Once the tab is closed, the terminal becomes eligible for culling after the idle timeout.

**Sessions**: Based on the associated kernel's `last_activity`.

> **Note**: Terminal culling sends SIGHUP to the terminal process. Processes started with `nohup` will survive culling.

## Installation

Requires JupyterLab 4.0.0 or higher.

```bash
pip install jupyterlab-kernel-terminal-workspace-culler-extension
```

## Configuration

Open JupyterLab Settings (`Settings` -> `Settings Editor`) and search for "Resource Culler" to adjust timeouts and enable/disable culling for each resource type.

## Logs

Culling actions are logged at INFO level with `[Culler]` prefix:

```
[Culler] CULLING KERNEL abc123 - idle 65.2 minutes (threshold: 60)
[Culler] Kernel abc123 culled successfully
[Culler] CULLING TERMINAL 1 - idle 62.1 minutes (threshold: 60)
[Culler] Terminal 1 culled successfully
```

Run JupyterLab with `--log-level=INFO` to see culling activity.

## FAQ

**Q: My long-running calculation was killed. How do I prevent this?**

Two options:
1. **Increase timeout**: Go to `Settings` -> `Settings Editor` -> `Resource Culler` and increase the kernel/terminal timeout
2. **Use a terminal multiplexer**: Run calculations inside `screen` or `tmux` - these survive terminal culling

```bash
# Using screen
screen -S mysession
python long_calculation.py
# Detach with Ctrl+A, D

# Using tmux
tmux new -s mysession
python long_calculation.py
# Detach with Ctrl+B, D
```

**Q: Will closing my browser tab kill my running process?**

For terminals: By default, terminals are only culled when the browser tab is closed (disconnected). After closing the tab, the terminal will be culled once the idle timeout expires. Foreground processes receive SIGHUP. Use `nohup`, `screen`, or `tmux` for processes that must survive.

For kernels: The kernel continues running. Activity is tracked server-side, so a busy kernel won't be culled even if the browser is closed.

**Q: What happens to processes started with `nohup`?**

They survive terminal culling. `nohup` makes processes ignore SIGHUP, which is the signal sent when a terminal closes.

**Q: How do I disable culling entirely?**

Go to `Settings` -> `Settings Editor` -> `Resource Culler` and uncheck "Enable Kernel Culling" and "Enable Terminal Culling".

**Q: Can I see when resources were culled?**

Yes. Run JupyterLab with `--log-level=INFO` to see `[Culler]` log messages. If you have `jupyterlab-notifications` installed, you'll also see toast notifications.

## CLI

The extension includes a command-line tool for listing and culling resources from the terminal.

```bash
# Show help
jupyterlab_kernel_terminal_workspace_culler

# List all resources and their idle times
jupyterlab_kernel_terminal_workspace_culler list

# List as JSON
jupyterlab_kernel_terminal_workspace_culler list --json

# Show what would be culled (dry run)
jupyterlab_kernel_terminal_workspace_culler cull --dry-run

# Cull idle resources
jupyterlab_kernel_terminal_workspace_culler cull

# Custom timeouts
jupyterlab_kernel_terminal_workspace_culler cull --kernel-timeout 30 --terminal-timeout 120
```

The CLI auto-discovers running Jupyter servers. You can also set environment variables:
- `JUPYTER_SERVER_URL` - server URL (e.g., `http://localhost:8888/`)
- `JUPYTER_TOKEN` - authentication token

## Uninstall

```bash
pip uninstall jupyterlab-kernel-terminal-workspace-culler-extension
```
