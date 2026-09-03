# Acceptance Criteria - JupyterLab Resource Culler

What the extension guarantees when it ends an idle kernel, terminal or workspace. The periodic culler runs server-side on a fixed interval; the frontend reports which terminals a browser has open, terminado's per-terminal websocket clients are the ground truth behind those reports, and workspace layout files say which terminals a workspace still holds.

## Authors

- `@kj` Konrad Jelen

## Terminal culling `TERM`

which terminals the periodic culler may end, and how it knows one really ended

- [x] `ACC-TERM-1` **Idle terminal culled** - HIGH; a terminal idle past `terminalCullIdleTimeout` with no tab evidence and no workspace reference is terminated
  - evidence: tests/test_culler.py::TestCullIdleTerminal::test_cull_idle_terminal, 75 pytest green
  - test: list one terminal with last_activity 120 minutes old, assert terminate is called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:07Z @kj added
  - log: 2026-09-03T15:59:07Z @kj closed
- [x] `ACC-TERM-2` **Open tab protects** - CRITICAL; a terminal with a live terminado websocket client is never culled, whatever the frontend reports say
  - related: DEF-TERM-9 - the throttled-tab cull this prevents
  - evidence: tests/test_culler.py::TestWebsocketTabProtection::test_ws_connected_terminal_not_culled_without_reports and test_ws_connected_terminal_not_culled_with_stale_reports
  - test: register a pty carrying one attached client, assert terminate is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:07Z @kj added
  - log: 2026-09-03T15:59:07Z @kj closed
- [x] `ACC-TERM-3` **Frontend report protects** - HIGH; a terminal named in any client's active-terminals report, inside that client's TTL, is never culled
  - evidence: tests/test_culler.py::TestCullIdleTerminal::test_connected_terminal_not_culled
  - test: post one client report naming the terminal, assert terminate is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:07Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-4` **One client cannot clobber another** - HIGH; a client reporting no terminals never removes protection another client reported
  - evidence: tests/test_culler.py::TestActiveTerminals::test_empty_report_does_not_clobber and test_union_across_clients
  - test: two clients, one reporting the terminal and one reporting none, assert terminate is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-5` **Report TTL is per client** - MEDIUM; report staleness is judged against the reporting client's own interval, not the server's
  - evidence: tests/test_culler.py::TestActiveTerminals::test_client_judged_against_own_interval
  - test: report at a 30-minute cadence against a 5-minute server interval, assert the report is still fresh
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-6` **Disconnect grace** - HIGH; a terminal becomes cull-eligible one full idle timeout after its last tab evidence, not on the next check
  - evidence: tests/test_culler.py::TestDisconnectGrace::test_recently_disconnected_terminal_not_culled and test_grace_expires_after_full_timeout
  - test: attach then detach a client, assert no cull inside the timeout and a cull past it
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-7` **Workspace reference protects** - CRITICAL; a terminal referenced by any existing workspace is never culled
  - related: DEF-TERM-19 - the grace-anchor ordering behind the cascade
  - evidence: tests/test_culler.py::TestWorkspaceTerminalProtection::test_workspace_referenced_terminal_never_culled
  - test: list a workspace holding `terminal:1` in its data, assert terminal 1 is not culled
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-8` **Edge: workspace references unreadable** - CRITICAL; when the workspace listing fails, no terminal is culled in that pass
  - evidence: tests/test_culler.py::TestWorkspaceTerminalProtection::test_listing_failure_fails_safe
  - test: raise from list_workspaces, assert terminate is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-9` **Culled means gone** - HIGH; a terminal is reported culled only once it has left the terminal manager's registry, never on the strength of the terminate call
  - related: DEF-TERM-21 - the endless cull loop this closes
  - evidence: tests/test_culler.py::TestDefunctTerminalReap::test_survivor_is_not_reported_as_culled
  - test: leave the entry in the registry after terminate, assert the name is not in the culled list
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-10` **Defunct pty closed** - HIGH; a terminal still registered with a dead shell is closed through terminado's EOF path, freeing the entry and the pty master
  - related: DEF-TERM-21 - the defunct pty this reaps
  - evidence: tests/test_culler.py::TestDefunctTerminalReap::test_defunct_terminal_is_closed_by_hand and test_eof_failure_still_drops_the_entry
  - test: registry entry whose ptyproc.isalive() is False, assert on_eof runs and the entry is dropped
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-11` **Edge: terminal survives the cull** - MEDIUM; a terminal that survives a cull attempt is attempted once and skipped on every later pass
  - evidence: tests/test_culler.py::TestDefunctTerminalReap::test_survivor_is_not_attempted_again
  - test: live shell that ignores terminate, run two passes, assert one terminate call
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:08Z @kj closed
- [x] `ACC-TERM-12` **Live shell left alone** - MEDIUM; a terminal whose shell is still alive is never closed behind terminado's back
  - evidence: tests/test_culler.py::TestDefunctTerminalReap::test_live_shell_that_survives_is_left_alone
  - test: registry entry whose ptyproc.isalive() is True, assert on_eof is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:08Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-TERM-13` **Disconnected-only can be turned off** - MEDIUM; with `terminalCullDisconnectedOnly` false, an idle terminal is culled even with an open tab
  - evidence: tests/test_culler.py::TestCullIdleTerminal::test_disconnected_only_off_culls_connected
  - test: set the setting false, attach a client, assert the idle terminal is culled
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-TERM-14` **Edge: manager without a registry** - LOW; a terminal manager exposing no `terminals` registry falls back to frontend reports instead of failing the pass
  - evidence: tests/test_culler.py::TestWebsocketTabProtection::test_manager_without_registry_falls_back_to_reports
  - test: manager mock with no terminals attribute, assert reports still protect
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed

## Workspace culling `WSPACE`

which workspaces are cull-eligible, where they are read from, and the cascade into their terminals

- [x] `ACC-WSPACE-15` **Auto workspaces only** - CRITICAL; only ids starting `auto-` are cull-eligible; a named workspace is never deleted
  - evidence: tests/test_culler.py::TestCullWorkspaces::test_cull_auto_only and test_named_workspace_preserved
  - test: list one auto-0 and one named workspace past the timeout, assert only auto-0 is deleted
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-16` **Default layout never culled** - CRITICAL; the default workspace is never deleted, with or without a leading slash
  - evidence: tests/test_culler.py::TestCullWorkspaces::test_default_never_culled
  - test: list `default` and `/default` past the timeout, assert delete is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-17` **Idle threshold honoured** - HIGH; an `auto-*` workspace younger than `workspaceCullIdleTimeout` is kept
  - evidence: tests/test_culler.py::TestCullWorkspaces::test_recent_auto_not_culled
  - test: list a recently used auto-0, assert delete is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-18` **Cascade order** - HIGH; workspaces are culled before terminals, so a workspace culled this pass releases its terminals in the same pass
  - evidence: tests/test_culler.py::TestWorkspaceTerminalProtection::test_cascade_workspace_culled_then_terminal
  - test: idle auto-0 referencing terminal 1, assert both go in one call to the culler
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-19` **Cascade blocked by a survivor** - HIGH; a terminal still referenced by a surviving workspace is not released when another workspace holding it is culled
  - evidence: tests/test_culler.py::TestWorkspaceTerminalProtection::test_cascade_blocked_by_surviving_workspace
  - test: two workspaces referencing terminal 1, one idle and one recent, assert the terminal survives
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-20` **Grace survives reference loss** - MEDIUM; a terminal that loses its workspace reference still gets the full disconnect grace before it is eligible
  - evidence: tests/test_culler.py::TestWorkspaceTerminalProtection::test_grace_survives_reference_loss
  - test: reference then drop it, assert no cull on the next pass
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:09Z @kj closed
- [x] `ACC-WSPACE-21` **Workspaces directory comes from the server** - MEDIUM; the culler reads the server's configured workspaces directory, honouring the `workspaces_dir` trait and `JUPYTERLAB_WORKSPACES_DIR`
  - evidence: tests/test_culler.py::TestWorkspacesDirResolution::test_extension_app_trait_wins and test_env_var_honoured_without_trait
  - test: set the trait on a loaded extension app, assert it wins over the config-dir default
  - test-tags: UNIT
  - log: 2026-09-03T15:59:09Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed

## Kernel culling `KERN`

which kernels the periodic culler may shut down

- [x] `ACC-KERN-22` **Busy kernel protected** - CRITICAL; a kernel whose execution_state is busy is never shut down, however long since its last activity
  - evidence: tests/test_culler.py::TestCullIdleKernel::test_skip_busy_kernel
  - test: kernel busy with last_activity 120 minutes old, assert shutdown_kernel is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-KERN-23` **Idle kernel culled** - HIGH; a kernel idle past `kernelCullIdleTimeout` is shut down
  - evidence: tests/test_culler.py::TestCullIdleKernel::test_cull_idle_kernel
  - test: idle kernel 120 minutes old against a 60-minute timeout, assert shutdown_kernel is called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-KERN-24` **Recent activity protects** - HIGH; a kernel active inside the timeout is kept
  - evidence: tests/test_culler.py::TestCullIdleKernel::test_skip_active_kernel
  - test: kernel active 5 minutes ago, assert shutdown_kernel is not called
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed

## Settings `CONFIG`

how settings reach the server and which values it accepts

- [x] `ACC-CONFIG-25` **Atomic apply** - HIGH; a settings payload carrying one invalid value changes nothing and answers 400
  - evidence: tests/test_culler.py::TestUpdateSettings::test_bad_type_rejected_without_partial_apply
  - test: post a valid bool with an invalid int, assert the bool did not change and the status is 400
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-CONFIG-26` **Exact types** - HIGH; a bool where an int is expected, and a numeric string, are both rejected
  - evidence: tests/test_culler.py::TestUpdateSettings::test_bool_rejected_for_int_setting and test_bool_string_rejected
  - test: post a bool and a numeric string as kernelCullIdleTimeout, assert both raise
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-CONFIG-27` **One minute floor** - MEDIUM; timeouts and the check interval clamp to at least one minute, whatever the payload says
  - evidence: tests/test_culler.py::TestUpdateSettings::test_clamp_timeouts_and_interval
  - test: post 0 and a negative value, assert both read back as 1
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-CONFIG-28` **Edge: undecodable body** - MEDIUM; a non-object body, invalid UTF-8, or pathologically nested JSON answers 400, never 500
  - evidence: tests/test_routes.py, the non-object, invalid-UTF-8 and deep-nesting cases
  - test: post a bare number, an invalid-UTF-8 body and 200000 open brackets to each POST route, assert 400
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed
- [x] `ACC-CONFIG-29` **Unknown keys ignored** - LOW; a payload key the server does not know is ignored rather than rejected
  - evidence: tests/test_culler.py::TestUpdateSettings::test_unknown_keys_ignored
  - test: post an unknown key alongside a known one, assert the known one applied
  - test-tags: UNIT
  - log: 2026-09-03T15:59:10Z @kj added
  - log: 2026-09-03T15:59:10Z @kj closed

## Command line `CLI`

the `culler` command: server resolution, and what it does when it cannot see the truth

- [x] `ACC-CLI-30` **Fail closed on unknown connection status** - HIGH; when the connection endpoint is unavailable, `cull` skips terminals entirely and exits 1
  - evidence: tests/test_cli.py::TestCmdCullFailClosed::test_endpoint_failure_skips_terminal_culling
  - test: connection endpoint returning None, assert no terminate call and exit code 1
  - test-tags: UNIT
  - log: 2026-09-03T15:59:11Z @kj added
  - log: 2026-09-03T15:59:11Z @kj closed
- [x] `ACC-CLI-31` **Connected terminals skipped** - HIGH; `cull` never terminates a terminal the server reports as connected
  - evidence: tests/test_cli.py::TestCmdCullFailClosed::test_connected_terminal_skipped
  - test: connection status True for the idle terminal, assert no terminate call
  - test-tags: UNIT
  - log: 2026-09-03T15:59:11Z @kj added
  - log: 2026-09-03T15:59:11Z @kj closed
- [x] `ACC-CLI-32` **include-connected bypasses the check** - MEDIUM; `--include-connected` culls idle terminals without consulting connection status at all
  - evidence: tests/test_cli.py::TestCmdCullFailClosed::test_include_connected_bypasses_check
  - test: pass the flag, assert the connection endpoint is never queried and the terminal is terminated
  - test-tags: UNIT
  - log: 2026-09-03T15:59:11Z @kj added
  - log: 2026-09-03T15:59:11Z @kj closed
- [x] `ACC-CLI-33` **Workspace endpoint failure is an error** - MEDIUM; an unavailable workspace endpoint is reported on stderr with exit 1, never as nothing to cull
  - evidence: tests/test_cli.py::TestCmdCullFailClosed::test_workspace_endpoint_failure_is_an_error
  - test: workspace culling returning None, assert exit 1 and a stderr line naming workspaces
  - test-tags: UNIT
  - log: 2026-09-03T15:59:11Z @kj added
  - log: 2026-09-03T15:59:11Z @kj closed
- [x] `ACC-CLI-34` **Server resolution order** - MEDIUM; the server is resolved as flag, then `JUPYTER_SERVER_URL`, then auto-detection, with the environment token chain applied in every branch
  - evidence: tests/test_cli.py::TestServerResolution::test_flag_wins, test_env_var_used_when_no_flag and test_flag_url_falls_back_to_env_token
  - test: set the env var with and without the flag, assert the url and token chosen
  - test-tags: UNIT
  - log: 2026-09-03T15:59:11Z @kj added
  - log: 2026-09-03T15:59:11Z @kj closed
