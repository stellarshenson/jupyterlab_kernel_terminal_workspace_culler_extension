---
name: jupyterlab-kernel-terminal-workspace-culler-extension
description: List and cull idle Jupyter kernels, terminals and workspaces on a running Jupyter server, through the `jupyterlab_kernel_terminal_workspace_culler` CLI of jupyterlab_kernel_terminal_workspace_culler_extension. Use when checking what is idle on a JupyterLab server, freeing memory held by idle kernels or terminals, deleting old workspaces, reading the Resource Culler settings in effect, or "cull idle kernels".
---

# jupyterlab_kernel_terminal_workspace_culler

Runs on Jupyter server machine. Talks to server REST API and culler extension loaded in it. Commands, flags, output, environment, exit codes: `jupyterlab_kernel_terminal_workspace_culler --help`, `jupyterlab_kernel_terminal_workspace_culler <command> --help`. Read first.

## Rules

- Ask user before `cull`. Cannot undo: kernel variables lost, terminal shell killed, workspace layout deleted
- `cull --dry-run` first, show user the rows, then `cull` with same flags
- `cull` uses its own flag timeouts, not user's Resource Culler settings. Want user's values: `list --json`, read `culler.settings`, pass them as flags
- Never `--include-connected` unless user asked. Kills terminal user has open in a tab
- Exit 0 no proof all culled. Read `action` of each row: `failed` = still there
- Token is secret. Leave `--token` off; CLI finds server and token itself. Never print `jupyter server list` output
