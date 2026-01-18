# Changelog

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
