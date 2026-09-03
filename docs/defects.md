# Defects - JupyterLab Resource Culler

`[ ]` open, `[x]` fixed. Dated notes under each track how it evolved. DEF-1..DEF-7 surfaced in a bug-hunter adversarial review (2026-07-15); DEF-8 found while fixing them; DEF-9 reported by the user (2026-07-16); DEF-10..DEF-16 surfaced in round 1 of the follow-up adversarial review of the DEF-9 fix, DEF-17..DEF-20 in rounds 2-4 (2026-07-16).

## Authors

- `@kj` Konrad Jelen

## Terminal culling `TERM`

the periodic terminal culler: which terminals it may end, and whether it really ended them

- [x] `DEF-TERM-1` **multi-client active-terminals clobber culls a connected terminal** - MAJOR; MEDIUM-HIGH; backend kept one global active-terminals set that every frontend POST replaced wholesale, so a second tab reporting `[]` wiped the protection and an idle-but-open terminal got SIGHUP'd; cause: single shared `set[str]`, last-writer-wins; fix: per-client tracking keyed by `clientId` with a stale-after-2-intervals TTL union; `culler.py`, `routes.py`, `src/index.ts`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter adversarial review, Round 1
  - log: 2026-07-15T00:00:00Z @kj fixed: `_active_terminals_by_client` union + TTL prune; frontend sends a stable per-load `clientId`; pytest 32 green
  - log: 2026-07-15T00:00:00Z @kj hardened: Round 2 review flagged a tight TTL grace; widened to 3 intervals and the frontend now re-reports immediately when it (re)arms the interval
  - log: 2026-09-03T16:15:12Z @kj edited severity
- [x] `DEF-TERM-9` **open-tab terminal culled when its browser tab is throttled** - MAJOR; a terminal with an open tab in a backgrounded/frozen browser tab (or a slept laptop) got culled: browsers throttle timers, the frontend report goes stale past the 3-interval TTL, and protection vanished; README promised the WebSocket check but the code only ever trusted frontend reports; cause: `_terminal_has_active_tab` used report union only; fix: check terminado's `PtyWithClients.clients` (live websocket per open tab, throttle-immune) as ground truth, reports remain a secondary signal; `culler.py`
  - log: 2026-07-16T00:00:00Z @kj reported: user observed terminals with open tabs being culled despite DEF-1 fix
  - log: 2026-07-16T00:00:00Z @kj fixed: `_terminal_has_ws_client` checks `terminal_manager.terminals[name].clients`; `_terminal_has_active_tab` ORs it with the report union; falls back to reports for managers without a `.terminals` registry; 5 new tests, 37 pytest green
- [x] `DEF-TERM-12` **websocket protection dies permanently after frontend reconnect exhaustion** - MEDIUM; JupyterLab retries a lost terminal websocket only ~7 times over ~2 min, then stays disconnected with the tab still open; `PtyWithClients.clients` goes empty forever and protection fell back to the throttle-prone reports - the DEF-9 bug through a different door; cause: no memory of when a terminal was last seen connected; fix: `_terminal_tab_last_seen` grants a full idle-timeout grace from the moment tab evidence disappeared (also the semantics the README documents: "eligible after the idle timeout once the tab is closed"); `culler.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1 of the DEF-9 fix
  - log: 2026-07-16T00:00:00Z @kj fixed: last-seen stamped on every check while a tab is live; effective idle counts from max(last_activity, tab_last_seen); entries pruned when terminals vanish; 3 tests
- [x] `DEF-TERM-13` **report-TTL judged against the wrong interval after a cadence change** - MEDIUM; backend computed staleness from ITS current interval while clients report at THEIR configured cadence - after an interval change every not-yet-reloaded client's reports went permanently stale (and a failed settings POST left the frontend committed to a cadence the backend never learned); cause: single server-side `max_age`, frontend committed interval before POST success; fix: each report carries `intervalMinutes` and staleness is per-client; frontend commits a new interval only after a successful settings POST; `culler.py`, `routes.py`, `src/index.ts`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1; impact gated to paths where the ws signal is unavailable
  - log: 2026-07-16T00:00:00Z @kj fixed: per-client TTL + commit-after-ack; bogus `intervalMinutes` falls back to the server interval
- [x] `DEF-TERM-15` **per-client report map grows without bound** - MINOR; with `terminalCullEnabled=false` or `terminalCullDisconnectedOnly=false` the pruning path never ran while every page load minted a new clientId and kept POSTing - one leaked entry per reload for the server's lifetime; cause: pruning only inside `_active_terminal_names`; fix: `set_active_terminals` prunes stale clients on every write; `culler.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1
  - log: 2026-07-16T00:00:00Z @kj fixed: prune-on-write via extracted `_prune_stale_clients`
- [x] `DEF-TERM-19` **workspace-reference skip starved the disconnect-grace anchor** - MEDIUM; the new workspace-reference protection skipped referenced terminals BEFORE stamping tab evidence, and an open-tab terminal is virtually always also workspace-referenced - so no grace anchor was ever recorded and a terminal was culled within one check interval of its reference disappearing (tab closed, workspace culled) instead of getting the documented full-timeout grace; cause: check ordering introduced with the cascade; fix: tab check (which stamps `_terminal_tab_last_seen`) runs before the reference skip; `culler.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 3, interaction between the cascade and the DEF-12 grace
  - log: 2026-07-16T00:00:00Z @kj fixed: reordered checks; regression test covers the referenced-while-open -> reference-lost path
- [x] `DEF-TERM-17` **zombie widget plus terminado name reuse made an unrelated terminal immortal** - MEDIUM; with the standard JupyterLab setting `closeOnExit: false`, a terminal killed server-side leaves its widget attached holding a disposed session that still returns its old name; terminado reuses the lowest free integer name, so the zombie's reports protected an unrelated new terminal indefinitely; cause: report filter checked `isAttached`/`!isDisposed` on the widget but never `session.isDisposed`; fix: skip disposed sessions in `reportActiveTerminals`; `src/index.ts`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 2
  - log: 2026-07-16T00:00:00Z @kj fixed: `!session.isDisposed` guard in the report filter
- [x] `DEF-TERM-21` **endless cull loop on a defunct terminal whose pty an orphan holds open** - MAJOR; a terminal whose shell exited but whose pty slave is still held open by a process that outlived it (a stopped job reparented to PID 1) is culled every check interval forever: 236 'culled successfully' messages for one terminal in a day, idle time climbing past 1135 minutes instead of resetting, one notification per pass; the registry entry, the pty master fd and the ioloop handler leak for the life of the server; `culler.py`
  - evidence: 6 tests in `tests/test_culler.py::TestDefunctTerminalReap` plus the force=True assertions in 2 existing cull tests; 75 pytest green on the fix, 7 of those 8 fail when `culler.py` is reverted (the 8th, no-reap-on-a-live-shell, passes there because the previous code reaped nothing)
  - repro: in a lab terminal run a process that survives SIGHUP (`claude`, then Ctrl-Z to stop it), exit the shell, wait past terminalCullIdleTimeout: every pass logs 'Terminal N culled successfully' and the terminal stays in `GET /api/terminals`
  - test-tags: UNIT
  - root-cause: 2026-09-03T16:15:12Z @kj terminado removes a terminal from its registry only in `NamedTermManager.on_eof`, which fires when the pty master reads EOF; that cannot happen while any process holds the slave open, so the entry is immortal by construction. `PtyWithClients.terminate` returns True immediately when `ptyproc.isalive()` is False (the early return before any signal), `NamedTermManager.terminate` discards that bool, and the culler logged success without checking the registry, so every pass re-found the same terminal
  - log: 2026-09-03T16:15:12Z @kj added
  - log: 2026-09-03T16:15:12Z @kj verified against the installed sources: terminado 0.18.1 `management.py` drops an entry only in `NamedTermManager.on_eof` (line 421), `PtyWithClients.terminate` returns True before signalling when `isalive()` is False (line 113), `NamedTermManager.terminate` returns None (line 416); `jupyter_server_terminals/terminalmanager.py:168` shows upstream's own culler passing force=True where this extension passed nothing
  - log: 2026-09-03T16:15:12Z @kj fixed: `terminate(name, force=True)`; `_terminal_removed` reads the registry as the outcome signal; `_reap_defunct_terminal` runs `on_eof` by hand when the entry survives and the shell is dead, then pops the entry even if `on_eof` raised; `_terminal_cull_failed` skips a terminal that survived anyway, so one stuck terminal costs one attempt rather than one per interval; the orphan process is left alone
  - log: 2026-09-03T16:15:12Z @kj residual, filed separately: the CLI terminates through jupyter's own `DELETE /api/terminals/<name>`, which cannot reap and answers 204 regardless
  - log: 2026-09-03T16:15:12Z @kj closed

## Workspace culling `WSPACE`

workspace culling and the directory it reads, including the cascade that releases a culled workspace's terminals

- [x] `DEF-WSPACE-2` **workspace culler deleted named workspaces, not just auto-\** - MEDIUM; * - MEDIUM; docs and schema scope culling to "auto-0, auto-k, etc." but the code culled every non-default workspace past timeout, so a saved named layout was removed after 7 days; cause: guard skipped only `id == "default"`; fix: restrict eligibility to ids starting `auto-` via `_is_cullable_workspace`; `culler.py`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter review; confirmed against `schema/plugin.json` scope text
  - log: 2026-07-15T00:00:00Z @kj fixed: auto-only eligibility in `_cull_workspaces` and `cull_workspaces_with_timeout`
  - log: 2026-09-03T16:15:12Z @kj edited severity
- [x] `DEF-WSPACE-3` **hardcoded workspaces directory ignores JUPYTER_CONFIG_DIR** - MINOR; workspace culling silently no-op'd where the jupyter config dir is relocated because the path was pinned to `~/.jupyter/lab/workspaces`; cause: `Path.home() / ".jupyter"` literal; fix: derive from `jupyter_core.paths.jupyter_config_dir()`; `culler.py`
  - log: 2026-07-15T00:00:00Z @kj reported: found during triage (reviewer missed it); fails safe but wrong
  - log: 2026-07-15T00:00:00Z @kj fixed: workspaces_dir now resolves from the active config dir
  - log: 2026-07-16T00:00:00Z @kj superseded: DEF-11 replaced this resolution with the server's own configured dir
- [x] `DEF-WSPACE-11` **workspace culler resolves its own dir, diverging from the live server's** - MEDIUM; with `JUPYTERLAB_WORKSPACES_DIR` or `--LabApp.workspaces_dir` set, the culler either silently culled nothing or deleted `auto-*` files belonging to ANOTHER deployment that used the default dir; cause: DEF-3 fix still hardcoded `jupyter_config_dir()/lab/workspaces` while jupyterlab_server builds its manager from the `workspaces_dir` trait; fix: `_resolve_workspaces_dir` prefers the loaded lab extension app's trait, then `jupyterlab.commands.get_workspaces_dir()` (honours the env var), then the config-dir default; `culler.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1 of the DEF-9 fix
  - log: 2026-07-16T00:00:00Z @kj fixed: trait -> env -> default resolution chain; 2 tests
- [x] `DEF-WSPACE-4` **default-workspace guard was a brittle exact string match** - MINOR; `id == "default"` would miss a `/default` form and could delete the primary layout on other clients; cause: unnormalized compare; fix: auto-only eligibility normalizes a leading slash so default and named ids never match; `culler.py`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter review, suspicion; held on this install
  - log: 2026-07-15T00:00:00Z @kj fixed: subsumed by the `auto-`-prefix guard (DEF-2)

## Settings `CONFIG`

settings applied through the REST handlers and the values the server accepts

- [x] `DEF-CONFIG-5` **no server-side clamp on timeouts/interval** - MINOR; an authenticated raw POST of a 0/negative timeout culled near-live resources and interval 0 broke the PeriodicCallback; cause: values assigned straight through, schema `minimum` is UI-only; fix: `max(1, ...)` clamp in `update_settings`; `culler.py`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter review
  - log: 2026-07-15T00:00:00Z @kj fixed: timeouts and interval floored to 1 before applying
- [x] `DEF-CONFIG-14` **REST handlers applied settings partially and accepted wrong types** - MINOR; `{"kernelCullEnabled": false, "kernelCullIdleTimeout": "abc"}` disabled kernel culling then 500'd (caller believes nothing applied); a string `"terminals": "12"` was iterated into bogus names `{"1","2"}` gaining protection; cause: assign-then-validate in `update_settings`, no type checks in `ActiveTerminalsHandler`; fix: `update_settings` validates every value before mutating anything (ValueError -> 400), active-terminals rejects non-list terminals / non-string clientId with 400; `culler.py`, `routes.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1; crafted authenticated requests only
  - log: 2026-07-16T00:00:00Z @kj fixed: atomic validated apply via `_SETTING_SPEC`; 6 tests across culler and routes
  - log: 2026-07-16T00:00:00Z @kj hardened: round 2 found JSON-valid non-object bodies (`5`, `[]`) 500-ing and `{"timeout": true}` on cull-workspaces computing a 60-second threshold that deleted every idle auto-\* workspace; all three POST handlers now require an object body and cull-workspaces validates timeout (int >= 1) and dry_run (bool) -> 400
  - log: 2026-07-16T00:00:00Z @kj hardened: round 3 found invalid UTF-8 bodies raising UnicodeDecodeError (a ValueError, not JSONDecodeError) -> 500 in two handlers; all three now catch it as 400
  - log: 2026-07-16T00:00:00Z @kj hardened: round 4 found pathologically nested JSON (`"["*200000`) raising RecursionError past the catch -> 500; added to the 400 tuple in all three handlers

## CLI `CLI`

the `culler` command line: server discovery, authentication, and what it reports as done

- [x] `DEF-CLI-6` **CLI `cull` ignored disconnected-only protection** - MEDIUM; `culler cull` terminated terminals with an open browser tab, unlike the periodic culler; cause: `cmd_cull` did no connection check although `cmd_list` fetched one; fix: skip connected terminals unless `--include-connected`; `cli.py`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter review; found independently in triage
  - log: 2026-07-15T00:00:00Z @kj fixed: `cmd_cull` queries `get_terminals_connection()` and skips connected terminals by default
- [x] `DEF-CLI-7` **CLI auto-detect silently targeted the first server** - MINOR; with multiple Jupyter servers running the CLI acted on whichever listed first; cause: `split("\n")[0]` with no signal; fix: warn on stderr naming the pick and suggesting `--server-url`; `cli.py`
  - log: 2026-07-15T00:00:00Z @kj reported: bug-hunter review; found independently in triage
  - log: 2026-07-15T00:00:00Z @kj fixed: multi-server warning emitted before use
- [x] `DEF-CLI-10` **CLI `cull` fails open when the connection endpoint errors** - MAJOR; if the extension endpoint failed (not loaded in the server's env, transient 500) `get_terminals_connection()` swallowed the exception into `{}`, every terminal then read as "disconnected", and open-tab terminals were terminated without `--include-connected`; cause: exception -> empty dict, consumer defaults missing names to False (= cullable); fix: endpoint failure now returns None, `cmd_cull` fails closed - skips terminal culling with a stderr error and exit code 1; `cull` with `--include-connected` and `list` (shows "unknown") are unaffected; `cli.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1 of the DEF-9 fix
  - log: 2026-07-16T00:00:00Z @kj fixed: None-propagating status + fail-closed cull path; 4 tests in new `tests/test_cli.py`
- [x] `DEF-CLI-16` **CLI `list` marked only "default" as protected** - MINOR; named workspaces and `auto-*` both showed unlabeled, implying named ones were cull-eligible while the server protects everything not starting `auto-`; cause: label check `ws_id == "default"` predates the DEF-2 semantics; fix: label mirrors `_is_cullable_workspace` (not `auto-*` prefix = protected); `cli.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 1
  - log: 2026-07-16T00:00:00Z @kj fixed: prefix-rule label in `cmd_list`
- [x] `DEF-CLI-20` **`JUPYTER_SERVER_URL` documented but never implemented** - MINOR; the CLI epilog, `--server-url` help, and README all instruct setting `JUPYTER_SERVER_URL`, yet no code read it - the CLI silently auto-detected and culled resources on the first local server instead of the intended one; cause: the env var was documented aspirationally; fix: `resolve_server_url_and_token` implements the chain flag > `JUPYTER_SERVER_URL` (with env token chain) > auto-detect; `cli.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 4; pre-existing, not a regression
  - log: 2026-07-16T00:00:00Z @kj fixed: env var honoured between the flag and auto-detection; 2 tests
  - log: 2026-07-16T00:00:00Z @kj hardened: final confirm found `--server-url` without `--token` dropping the env token chain (unauthenticated requests despite `JUPYTER_TOKEN` being documented unconditionally); token now falls back to the env chain in every branch
- [x] `DEF-CLI-18` **CLI workspace culling failed open and silent** - MINOR; against a server without the extension, `cull` printed "No workspaces to cull" and exited 0 while eligible workspaces existed, and `list` showed "(none)" - the opposite of the DEF-10 fail-closed semantics; cause: `cull_workspaces`/`list_workspaces` swallowed every exception into `[]`, indistinguishable from "nothing eligible"; fix: both return None on endpoint failure; `cull` reports a stderr error and exit 1, `list` shows "(culler extension unavailable)"; `cli.py`
  - log: 2026-07-16T00:00:00Z @kj reported: adversarial review round 2
  - log: 2026-07-16T00:00:00Z @kj fixed: None-propagating endpoints + fail-visible handling in both commands
- [ ] `DEF-CLI-22` **CLI reports a defunct terminal as terminated** - MINOR; `culler cull` terminates through jupyter's own `DELETE /api/terminals/<name>`, which answers 204 whether or not the terminal left the registry, so a terminal held open by a process that outlived its shell is printed as terminated and is still listed by the next `culler list`; the periodic culler reaps that case since DEF-TERM-21, the CLI cannot, because no route exposes the reap; `cli.py`
  - related: DEF-TERM-21 - the same defunct-pty case, reached through the REST path the periodic culler does not use
  - repro: leave a stopped process holding a pty after its shell exits, then run `culler cull --terminal-timeout 1`: it prints the terminal as terminated and `culler list` still shows it
  - test-tags: UNIT
  - root-cause: 2026-09-03T16:15:12Z @kj the reap lives in the server-side culler and there is no route to reach it from outside; `jupyter_server_terminals/api_handlers.py:83` calls `terminate(name, force=True)` and returns 204 unconditionally
  - log: 2026-09-03T16:15:12Z @kj added

## Tests `TESTS`

the test suites themselves, when they drift from the behaviour they claim to cover

- [x] `DEF-TESTS-8` **drifted test suite failed against current code** - MEDIUM; `test_culler.py` asserted removed session-culling settings and `test_routes.py` hit a non-existent `hello` endpoint (4+ failures); cause: tests never updated after the session->workspace redesign; fix: rewrote both suites to current behaviour and added DEF-1/2/4/5 coverage; `tests/test_culler.py`, `tests/test_routes.py`
  - log: 2026-07-15T00:00:00Z @kj reported: found while establishing the test baseline (4 failed, 15 passed)
  - log: 2026-07-15T00:00:00Z @kj fixed: 32 pytest tests green, including route integration tests
