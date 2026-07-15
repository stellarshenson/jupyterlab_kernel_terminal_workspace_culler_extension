# Defects - JupyterLab Resource Culler

`[ ]` open, `[x]` fixed. Dated notes under each track how it evolved. DEF-1..DEF-7 surfaced in a bug-hunter adversarial review (2026-07-15); DEF-8 found while fixing them.

## Terminal culling

- [x] `DEF-1` **multi-client active-terminals clobber culls a connected terminal** - MEDIUM-HIGH; backend kept one global active-terminals set that every frontend POST replaced wholesale, so a second tab reporting `[]` wiped the protection and an idle-but-open terminal got SIGHUP'd; cause: single shared `set[str]`, last-writer-wins; fix: per-client tracking keyed by `clientId` with a stale-after-2-intervals TTL union; `culler.py`, `routes.py`, `src/index.ts`
  - 2026-07-15 reported: bug-hunter adversarial review, Round 1
  - 2026-07-15 fixed: `_active_terminals_by_client` union + TTL prune; frontend sends a stable per-load `clientId`; pytest 32 green
  - 2026-07-15 hardened: Round 2 review flagged a tight TTL grace; widened to 3 intervals and the frontend now re-reports immediately when it (re)arms the interval

## Workspace culling

- [x] `DEF-2` **workspace culler deleted named workspaces, not just auto-\*** - MEDIUM; docs and schema scope culling to "auto-0, auto-k, etc." but the code culled every non-default workspace past timeout, so a saved named layout was removed after 7 days; cause: guard skipped only `id == "default"`; fix: restrict eligibility to ids starting `auto-` via `_is_cullable_workspace`; `culler.py`
  - 2026-07-15 reported: bug-hunter review; confirmed against `schema/plugin.json` scope text
  - 2026-07-15 fixed: auto-only eligibility in `_cull_workspaces` and `cull_workspaces_with_timeout`
- [x] `DEF-3` **hardcoded workspaces directory ignores JUPYTER_CONFIG_DIR** - LOW; workspace culling silently no-op'd where the jupyter config dir is relocated because the path was pinned to `~/.jupyter/lab/workspaces`; cause: `Path.home() / ".jupyter"` literal; fix: derive from `jupyter_core.paths.jupyter_config_dir()`; `culler.py`
  - 2026-07-15 reported: found during triage (reviewer missed it); fails safe but wrong
  - 2026-07-15 fixed: workspaces_dir now resolves from the active config dir
- [x] `DEF-4` **default-workspace guard was a brittle exact string match** - LOW; `id == "default"` would miss a `/default` form and could delete the primary layout on other clients; cause: unnormalized compare; fix: auto-only eligibility normalizes a leading slash so default and named ids never match; `culler.py`
  - 2026-07-15 reported: bug-hunter review, suspicion; held on this install
  - 2026-07-15 fixed: subsumed by the `auto-`-prefix guard (DEF-2)

## Settings

- [x] `DEF-5` **no server-side clamp on timeouts/interval** - LOW; an authenticated raw POST of a 0/negative timeout culled near-live resources and interval 0 broke the PeriodicCallback; cause: values assigned straight through, schema `minimum` is UI-only; fix: `max(1, ...)` clamp in `update_settings`; `culler.py`
  - 2026-07-15 reported: bug-hunter review
  - 2026-07-15 fixed: timeouts and interval floored to 1 before applying

## CLI

- [x] `DEF-6` **CLI `cull` ignored disconnected-only protection** - MEDIUM; `culler cull` terminated terminals with an open browser tab, unlike the periodic culler; cause: `cmd_cull` did no connection check although `cmd_list` fetched one; fix: skip connected terminals unless `--include-connected`; `cli.py`
  - 2026-07-15 reported: bug-hunter review; found independently in triage
  - 2026-07-15 fixed: `cmd_cull` queries `get_terminals_connection()` and skips connected terminals by default
- [x] `DEF-7` **CLI auto-detect silently targeted the first server** - LOW; with multiple Jupyter servers running the CLI acted on whichever listed first; cause: `split("\n")[0]` with no signal; fix: warn on stderr naming the pick and suggesting `--server-url`; `cli.py`
  - 2026-07-15 reported: bug-hunter review; found independently in triage
  - 2026-07-15 fixed: multi-server warning emitted before use

## Tests

- [x] `DEF-8` **drifted test suite failed against current code** - MEDIUM; `test_culler.py` asserted removed session-culling settings and `test_routes.py` hit a non-existent `hello` endpoint (4+ failures); cause: tests never updated after the session->workspace redesign; fix: rewrote both suites to current behaviour and added DEF-1/2/4/5 coverage; `tests/test_culler.py`, `tests/test_routes.py`
  - 2026-07-15 reported: found while establishing the test baseline (4 failed, 15 passed)
  - 2026-07-15 fixed: 32 pytest tests green, including route integration tests
