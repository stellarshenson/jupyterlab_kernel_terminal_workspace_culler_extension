# jupyterlab_kernel_terminal_workspace_culler_extension

[![GitHub Actions](https://github.com/stellarshenson/jupyterlab_kernel_terminal_workspace_culler_extension/actions/workflows/build.yml/badge.svg)](https://github.com/stellarshenson/jupyterlab_kernel_terminal_workspace_culler_extension/actions/workflows/build.yml)
[![npm version](https://img.shields.io/npm/v/jupyterlab_kernel_terminal_workspace_culler_extension.svg)](https://www.npmjs.com/package/jupyterlab_kernel_terminal_workspace_culler_extension)
[![PyPI version](https://img.shields.io/pypi/v/jupyterlab-kernel-terminal-workspace-culler-extension.svg)](https://pypi.org/project/jupyterlab-kernel-terminal-workspace-culler-extension/)
[![Total PyPI downloads](https://static.pepy.tech/badge/jupyterlab-kernel-terminal-workspace-culler-extension)](https://pepy.tech/project/jupyterlab-kernel-terminal-workspace-culler-extension)
[![JupyterLab 4](https://img.shields.io/badge/JupyterLab-4-orange.svg)](https://jupyterlab.readthedocs.io/en/stable/)
[![Brought To You By KOLOMOLO](https://img.shields.io/badge/Brought%20To%20You%20By-KOLOMOLO-00ffff?style=flat)](https://kolomolo.com)
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-blue?style=flat)](https://www.paypal.com/donate/?hosted_button_id=B4KPBJDLLXTSA)

Automatically cull idle kernels, terminals, and workspaces after configurable timeout periods. Helps manage system resources by cleaning up unused sessions that accumulate during long JupyterLab usage.

## Features

- **Idle kernel culling** - Automatically shut down kernels that have been idle for a configurable duration
- **Idle terminal culling** - Close terminal sessions that haven't been used within the timeout period
- **Workspace cleanup** - Remove stale workspace state to free resources
- **Configurable timeouts** - Set idle time thresholds (in minutes) via JupyterLab settings
- **Server-side detection** - Accurately tracks activity via the server extension

## Installation

Requires JupyterLab 4.0.0 or higher.

```bash
pip install jupyterlab_kernel_terminal_workspace_culler_extension
```

## Uninstall

```bash
pip uninstall jupyterlab_kernel_terminal_workspace_culler_extension
```
