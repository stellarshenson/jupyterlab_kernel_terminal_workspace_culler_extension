# Changelog

## [1.0.24] - 2026-07-16

### Added

- Workspace-aware terminal protection with cull cascade: terminals referenced by any existing workspace are never culled; culling a workspace releases its terminals unless another surviving workspace still references them (cull order is now workspaces before terminals)
- Disconnect grace: a terminal becomes cull-eligible one full idle timeout after its last tab evidence disappears, covering exhausted websocket reconnects and sleep/wake
- CLI honours the documented `JUPYTER_SERVER_URL` environment variable and falls back to the env token chain in every server-resolution branch

### Fixed

- Terminals with open tabs are no longer culled when browser tab throttling stalls frontend reports - the culler now checks terminado's per-terminal websocket clients as ground truth
- CLI `cull` fails closed when the extension endpoint is unavailable instead of terminating open-tab terminals; workspace culling likewise reports an error instead of silent success
- Workspace culler uses the server's configured workspaces directory (`workspaces_dir` trait, `JUPYTERLAB_WORKSPACES_DIR`) instead of resolving its own
- Frontend report staleness is judged against each client's own cadence; a failed settings sync no longer desynchronizes the report interval
- REST handlers validate input atomically (wrong types, non-object or undecodable bodies return 400; a boolean `timeout` no longer computes a 60-second threshold that deleted workspaces)
- Zombie terminal widgets (terminal killed server-side with `closeOnExit: false`) no longer protect unrelated terminals after terminado reuses the name
- CLI `list` marks every non-`auto-*` workspace as protected, matching the server rule

## [1.0.23] - 2026-07-15

### Added

- CLI `cull` skips terminals with an open browser tab by default; `--include-connected` culls them anyway
- CLI warns when multiple Jupyter servers are detected during auto-discovery

### Changed

- Updated build Makefile to v1.34 (project-local nodeenv, prettier via jlpm)

### Fixed

- Per-client active-terminal tracking so a terminal open in one browser tab is no longer culled when another tab reports none
- Workspace culling now targets only auto-generated workspaces (`auto-*`); named and default workspaces are always preserved
- Workspaces directory resolved from the active Jupyter config dir instead of a hardcoded `~/.jupyter` path
- Server-side clamp of culling timeouts and check interval to a minimum of 1 minute
- Rewrote the drifted Python test suite to current behaviour (32 tests pass)

<!-- <START NEW CHANGELOG ENTRY> -->

## 1.0.2

- First stable release

### Fixed

- Malformed GitHub URLs in package.json (homepage, bugs.url, repository.url)

<!-- <END NEW CHANGELOG ENTRY> -->

## 0.1.8

### Added

- CI/CD workflows for build, check-release, prep-release, publish-release, and PR label enforcement
- Default Settings table in README
- How Idle Detection Works documentation section
- FAQ section with guidance on long-running calculations, screen/tmux usage, and disabling culling

### Fixed

- Terminal manager access in JupyterHub environments (fallback to `web_app.settings`)
- Notification display showing literal `<br>` tags (changed to `\n` newlines)
- TypeScript lib0 declaration errors (`skipLibCheck: true`)

### Changed

- Default timeouts: kernel 60min, terminal 60min, session 10080min (7 days)

## 0.1.1

### Added

- Server-side `ResourceCuller` class using tornado `PeriodicCallback`
- Kernel culling based on `execution_state` and `last_activity`
- Terminal culling based on WebSocket activity
- Session culling based on associated kernel activity
- REST handlers: `/settings`, `/status`, `/cull-result`
- Frontend settings sync via `ISettingRegistry`
- Notification polling with jupyterlab-notifications integration
- 8 configurable settings in schema/plugin.json
- Unit tests with pytest-asyncio

## 0.1.0

### Added

- Initial project structure for JupyterLab 4.x extension
- TypeScript frontend with Python server extension
- Claude Code configuration and journal tracking
- README with standardized badges
