---
tags:
  - '#plan'
  - '#service-lifecycle'
date: '2026-05-30'
related:
  - '[[2026-05-30-service-lifecycle-adr]]'
  - '[[2026-05-30-service-lifecycle-research]]'
---

# `service-lifecycle` `silent-death cluster (atexit + heartbeat + divergence + log)` plan

Implements gh issue #113. Closes the three coupled gaps the Wave 1F
audit flagged: daemon never owns end-of-life cleanup, `service status` hides divergence, `service.log` has no lifecycle entries.

## Proposed Changes

- Daemon owns end-of-life: `atexit.register` + SIGTERM/SIGINT
  handlers in `service_lifespan` unlink `service.json` on clean
  exit; `service_lifespan` finally block does the same idempotent
  cleanup for ungraceful uvicorn shutdowns.
- Async heartbeat task writes `last_heartbeat` to `service.json`
  every 15s via `asyncio.to_thread` + atomic rewrite. Staleness
  threshold 60s.
- `handle_service_status` gathers four signals (file present, PID
  alive, port listening, heartbeat fresh) before rendering, then
  surfaces each as its own row plus a derived `State` row.
  Divergent / crashed-stale states exit with code 4.
- `service.lifecycle` log lines at WARNING level for startup +
  shutdown + reason, so they're visible at the default log
  threshold without operator opt-in.
- README + package README + rule file document the new contract.
- Tests + smoke walking the full lifecycle.

## Tasks

### Phase 1 — daemon heartbeat + atexit

1. Add module-level constants `_HEARTBEAT_INTERVAL_SECONDS = 15`
   and `_HEARTBEAT_STALENESS_SECONDS = 60` to
   `src/vaultspec_rag/mcp_server.py`.
1. Add `_status_file_path()` helper resolving the same path
   `cli._status_file()` uses (`{status_dir}/service.json`),
   sourced from `get_config()` so daemon and CLI stay in sync
   without cross-imports.
1. Add `_lifecycle_log(event: str, **kv)` helper that emits
   `service.lifecycle event=... key=value ...` at WARNING level.
1. Add `_heartbeat_loop()` async coroutine:
   - Sleeps `_HEARTBEAT_INTERVAL_SECONDS`.
   - Reads current `service.json` via `asyncio.to_thread`; if
     missing, exits the loop (heartbeat is best-effort, not a
     guarantee).
   - Updates `last_heartbeat` to `datetime.now(UTC).isoformat()`.
   - Writes atomically via `.tmp` + `os.replace`.
   - On `CancelledError`: returns.
   - On any other exception: logs WARNING and continues.
1. Add `_install_daemon_shutdown_hooks()`:
   - `atexit.register(_atexit_cleanup)` where
     `_atexit_cleanup` logs `event=shutdown reason=atexit` and
     unlinks `service.json` (idempotent).
   - `signal.signal(SIGTERM, ...)` and
     `signal.signal(SIGINT, ...)` invoking
     `_signal_cleanup(signum)` that logs
     `event=shutdown reason=signal signum=N`, unlinks the file,
     re-raises so uvicorn's own shutdown still runs.
1. Wire into `service_lifespan`:
   - Before `yield`: emit
     `event=startup pid=... port=...`, create the heartbeat task
     via `asyncio.create_task(_heartbeat_loop())`, call
     `_install_daemon_shutdown_hooks()`.
   - Finally block: cancel the heartbeat task with `await`+
     `CancelledError` swallow, log
     `event=shutdown reason=clean`, unlink `service.json`
     (idempotent — the atexit/signal path may have already done
     it).

### Phase 2 — CLI status divergence

1. `_read_service_status` (`src/vaultspec_rag/cli.py`): surface
   `last_heartbeat` in the returned dict when present (no
   validation failure when absent).
1. New `_port_is_listening(port: int) -> bool`: opens a TCP
   connection to `127.0.0.1:port` with a short timeout.
   Cheaper than `_health_probe` (no HTTP round-trip) and answers
   the "is anything listening" question directly.
1. New `_heartbeat_age_seconds(status: dict) -> float | None`:
   parses the `last_heartbeat` field and returns
   `now - parsed` seconds, or `None` when missing/unparseable.
1. Rewrite `handle_service_status` body:
   - Gather all four signals first.
   - Render rows: `Service JSON` / `PID Alive` / `Port Listening`
     / `Heartbeat` / `State`.
   - Derive `State`:
     - all-green -> `running`
     - file present + PID dead -> `crashed (PID dead)`
     - file present + PID alive + port not listening -> `crashed (port silent)`
     - file present + heartbeat stale (>60s) -> `crashed (heartbeat stale {age}s)`
     - file present + signals conflict otherwise -> `divergent`
     - no file -> `stopped`
   - Exit code: 0 for `running`, 3 for `stopped`, 4 for any
     `crashed*` or `divergent` state.

### Phase 3 — config + docs

1. `src/vaultspec_rag/config.py`: add optional
   `service_heartbeat_interval_seconds` and
   `service_heartbeat_staleness_seconds` defaults (15 / 60) for
   completeness, even though Phase 1 wires constants directly.
   Skipped if introducing a config field is more churn than
   value; the ADR explicitly accepts hard-coded constants for
   the first cut.
1. `README.md`: brief paragraph on heartbeat + divergence.
1. `src/vaultspec_rag/README.md`: extend the service-management
   section with the new `State` taxonomy and exit-code 4.
1. `.vaultspec/rules/rules/vaultspec-rag.builtin.md`: mention
   `service status` exit code 4 in the table.

### Phase 4 — tests

1. Unit tests in `tests/test_cli.py`:
   - `_heartbeat_age_seconds` parses valid + missing + malformed.
   - `_port_is_listening` true/false against an ephemeral
     socket the test opens.
   - `handle_service_status` State derivations: all-green,
     file-present + PID-dead (mock `_is_pid_alive`),
     heartbeat-stale (synthesize old timestamp in `service.json`),
     divergent, stopped. Use a tmp `service.json` written by the
     test, plus monkeypatching the helpers.
1. Unit tests in `tests/test_mcp_server.py`:
   - `_lifecycle_log` emits at WARNING with the expected format.
   - `_heartbeat_loop` writes `last_heartbeat` and tolerates a
     missing file (loop exits cleanly).
1. Integration test in `tests/integration/test_service_lifecycle.py`:
   - Start service, sleep > heartbeat interval, read
     `service.json`, confirm `last_heartbeat` updated.
   - Clean stop, confirm `service.json` gone and log contains
     `event=shutdown reason=clean`.
   - Simulate SIGKILL-equivalent (kill the process bypassing the
     shutdown handlers), confirm `service.json` survives but
     `_heartbeat_age_seconds` exceeds the staleness threshold;
     `service status` reports `crashed (heartbeat stale)` with
     exit code 4.

### Phase 5 — smoke + commit + PR

1. Smoke walkthrough: start service, `service status` reports
   `running` + fresh heartbeat. Clean stop, file gone, log shows
   `event=shutdown reason=clean`. Start, `kill -9` /
   PowerShell `Stop-Process -Force`, `service status` reports
   `crashed (heartbeat stale)` after 60s.
1. Commit each phase separately or as one `feat(service): daemon-side lifecycle + status divergence + log entries (#113)` — pick based on diff size at end of Phase 4.
1. Push, open PR linking #113. Ignore Gemini per standing
   instruction. Merge after CI green.

## Parallelization

Phase 1 (daemon) and Phase 2 (CLI status rendering) can land
together since they touch disjoint files, but Phase 2 tests need
Phase 1 wired so the heartbeat field exists end-to-end. Phase 3
docs depend on the final exit-code shape, do them last. Phase 4
test of the live integration depends on Phase 1 + 2 both shipping.

## Verification

- 209+ unit tests pass (was 196 + 13 new for Wave 2). ruff +
  mdformat + vault check schema clean.
- Smoke walkthrough on Windows (`port 18877`) confirmed:
  - `service status` with no file: exit 3, "stopped" state +
    `Service JSON: missing` divergence row.
  - Service started: status renders five divergence rows
    (`Service JSON: present`, `PID Alive: yes`, `PID Matches Service: yes`, `Port Listening: yes`, `Heartbeat: 9s ago`)
    plus `State: running` + full health/capabilities.
  - `last_heartbeat` advanced from 17:01:10 -> 17:01:25 over an
    18s sleep — exactly one `_HEARTBEAT_INTERVAL_SECONDS` tick.
  - `service.lifecycle event=startup pid=...` line lands in
    `service.log` at WARNING level (visible at the default
    threshold).
  - `server service stop`: `service.json` removed, exit clean.
- **Known Windows limitation**: `os.kill(pid, SIGTERM)` is
  `TerminateProcess` on Windows — the daemon never runs its
  atexit handler or lifespan `finally` on a `server service stop`, so the `event=shutdown reason=clean` line never reaches
  `service.log` on Windows. The CLI parent unlinks
  `service.json` itself (existing behaviour) so the file
  lifecycle is still correct; only the daemon-side shutdown log
  entry is missing. On POSIX the lifespan finally + atexit run
  normally. The CLI could mirror the log line itself if needed
  in a follow-up; not blocking for this issue.
  in the plan before merging the PR.
