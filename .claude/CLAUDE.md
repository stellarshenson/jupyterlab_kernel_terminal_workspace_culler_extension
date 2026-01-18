<!-- @import /home/lab/workspace/.claude/CLAUDE.md -->

# Project-Specific Configuration

This file imports workspace-level configuration from `/home/lab/workspace/.claude/CLAUDE.md`.
All workspace rules apply. Project-specific rules below strengthen or extend them.

The workspace `/home/lab/workspace/.claude/` directory contains additional instruction files
(MERMAID.md, NOTEBOOK.md, DATASCIENCE.md, GIT.md, JUPYTERLAB_EXTENSION.md, and others) referenced by CLAUDE.md.
Consult workspace CLAUDE.md and the .claude directory to discover all applicable standards.

## Mandatory Bans (Reinforced)

The following workspace rules are STRICTLY ENFORCED for this project:

- **No automatic git tags** - only create tags when user explicitly requests
- **No automatic version changes** - only modify version in package.json/pyproject.toml/etc. when user explicitly requests
- **No automatic publishing** - never run `make publish`, `npm publish`, `twine upload`, or similar without explicit user request
- **No manual package installs if Makefile exists** - use `make install` or equivalent Makefile targets, not direct `pip install`/`uv install`/`npm install`
- **No automatic git commits or pushes** - only when user explicitly requests
- **Always include package.json and package-lock.json** in commits - these files must be tracked in version control

## Project Context

JupyterLab extension to automatically cull idle kernels, terminals, and workspaces after configurable timeout periods. This helps manage system resources by cleaning up unused sessions.

**Technology Stack**:
- TypeScript frontend extension for JupyterLab 4.x
- Python server extension using jupyter_server
- Settings managed via JupyterLab settingregistry

**Package Names**:
- npm: `jupyterlab_kernel_terminal_workspace_culler_extension`
- PyPI: `jupyterlab-kernel-terminal-workspace-culler-extension`

## Strengthened Rules

- Follow JUPYTERLAB_EXTENSION.md for all extension development patterns
- Use `make install` for all dependency installation and builds
- Test changes with `make test` before requesting commits
