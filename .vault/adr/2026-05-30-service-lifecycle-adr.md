---
tags:
  - '#adr'
  - '#service-lifecycle'
date: '2026-05-30'
related:
  - '[[2026-05-30-service-lifecycle-research]]'
---

# `service-lifecycle` adr: `atexit unlink, async heartbeat, structured lifecycle log` | (**status:** `accepted`)

## Problem Statement

The vaultspec-rag HTTP daemon has no end-of-life cleanup or
liveness signal of its own. Three coupled symptoms:

- `service.json` survives every crash, SIGKILL, and startup
  exception, leaving a stale PID+port on disk that misleads
  `service status` and `_default_service_port`.
- `service status` consults its sources of truth sequentially and
  commits to a single verdict ("running") before the
  network probe completes, hiding divergence
  (PID alive but port not listening, or PID reused by an
  unrelated python process).
- `service.log` has no structured entries distinguishing clean
  shutdown from process disappearance, so post-mortem is reduced
  to "the log went quiet".

Issue #113 collects all three as the next safety milestone after
PR #109's hard-fail `--port` contract.

## Considerations

- The daemon today owns no part of the status-file lifecycle —
  the CLI parent writes on start and unlinks on stop. The
  separation is implicit and undocumented. Any daemon-side
  lifecycle work must (a) coexist with the CLI ownership without
  races and (b) be documented so the boundary stops being
  surprising.
- Default log level is `WARNING`. Existing `INFO` lifecycle lines
  in `service_lifespan` are silent in normal operation. New
  lifecycle entries must emit at `WARNING` or higher so they're
  visible without operator opt-in.
- The daemon is asyncio-native (FastMCP + uvicorn). A heartbeat
  background task should follow the existing
  `asyncio.create_task` pattern used for the file watcher in
  `_start_watcher` (`mcp_server.py` L268), with `asyncio.to_thread`
  for the synchronous JSON write so the event loop stays
  responsive.
- atexit alone is insufficient — `os._exit`, SIGKILL, and ungraceful
  uvicorn shutdowns skip it. Combine atexit with a SIGTERM/SIGINT
  signal handler that flushes a final log entry and unlinks the
  file before re-raising. SIGKILL stays unreachable by design;
  the heartbeat-staleness check is the safety net for that case.
- Heartbeat freshness is a derived property — adding
  `last_heartbeat` to the JSON schema is forward-compatible
  because `_read_service_status` only validates `pid`/`port`.
  No migration needed; existing callers ignore the new field.

## Constraints

- No new dependencies. Use stdlib `atexit` + `signal` +
  `asyncio.to_thread`.
- Atomic writes only. The heartbeat task must use the same
  `.tmp` + `os.replace` pattern as `_write_service_status` so a
  partial write never leaves a corrupted JSON file.
- `service status` must remain functional when the
  `last_heartbeat` field is absent (pre-upgrade `service.json`
  files, or daemons that crashed before the first heartbeat).
- Backwards compatibility: existing fields (`pid`, `port`,
  `started_at`) and their semantics stay. Existing exit codes
  for `service status` (0 = running, 3 = not running) stay.

## Implementation

### Daemon side (`src/vaultspec_rag/mcp_server.py`)

- New module-level constants
  `_HEARTBEAT_INTERVAL_SECONDS = 15` and
  `_HEARTBEAT_STALENESS_SECONDS = 60` so both halves of the
  contract live in one place.
- New `_status_file_path()` helper that mirrors the CLI's
  `_status_file()` (resolves status dir from config) so the
  daemon can find the file the CLI wrote without importing from
  `cli.py`.
- New `_heartbeat_loop()` async task. Every
  `_HEARTBEAT_INTERVAL_SECONDS` reads the current `service.json`,
  merges `last_heartbeat` (ISO-8601 UTC, second-resolution),
  writes atomically via `.tmp` + `os.replace`. On `CancelledError`
  exits cleanly. On any other exception, logs at WARNING and
  continues (heartbeat outage should not crash the service).
- New `_lifecycle_log(event, **kv)` helper: emits
  `service.lifecycle event={event} ...` at WARNING level so
  entries are visible at the default log threshold. Used for
  `event=startup`, `event=shutdown reason=clean|signal|atexit`.
- `service_lifespan` is extended:
  - On entry: log `event=startup pid=... port=...` after the
    existing "Service startup complete" line; create the
    heartbeat task; register `atexit` + SIGTERM/SIGINT handlers
    that unlink `service.json` and log `event=shutdown reason=atexit|signal`.
  - On exit: cancel heartbeat task, log `event=shutdown reason=clean`, unlink `service.json` (idempotent — already
    handled by atexit if signal hit first).

### CLI side (`src/vaultspec_rag/cli.py`)

- `_read_service_status` returns a richer dict (`last_heartbeat`
  surfaced when present) without changing the failure-mode
  semantics.
- `handle_service_status` is restructured:
  1. Gather all four signals unconditionally before rendering:
     `status_file = _read_service_status()`,
     `pid_alive`, `port_listening` (probed via TCP connect, not
     just `/health`), `heartbeat_age_seconds`.
  1. Render the table with one row per signal:
     `Service JSON: present|missing`,
     `PID Alive: yes|no|n/a`,
     `Port Listening: yes|no|n/a`,
     `Heartbeat: fresh (3s) | stale (90s) | absent`.
  1. Add a `State` row whose value is derived from the
     combination: `running` (all green), `divergent`
     (at least two signals disagree), `crashed-stale-pid`
     (file present, PID alive but not ours / not listening, or
     heartbeat stale), or `stopped` (no file).
  1. When `state == divergent` or `crashed-stale-pid`, exit
     with code 4 (new) so scripts can branch on
     "service is in a known-bad state" vs the existing 0/3.
- `_default_service_port` keeps its current behaviour (returns
  the port from `service.json` whenever the file is present and
  parseable); the heartbeat staleness check is rendered for the
  human but does not affect routing — fail-hard on dead `--port`
  is already shipped in PR #109.

### Log entries

All lifecycle entries use the structured `service.lifecycle`
logger name at WARNING level so they bubble past the default
`VAULTSPEC_RAG_LOG_LEVEL=WARNING` filter without operator
configuration.

## Rationale

A daemon-side atexit + SIGTERM handler is the smallest cut that
turns "the log went quiet" into "the log explicitly says I died
and how". The heartbeat exists for the unreachable case (SIGKILL,
OOM, kernel panic) where no in-process hook can fire — the file
ages instead of disappearing, and `service status` reports
that age.

A divergence row beats picking-one-and-hoping because the user
sees the full picture instead of a one-word verdict that
conflicts with the next row. Exit-code 4 lets `bash` /CI scripts
branch on it explicitly without ambiguity.

WARNING-level lifecycle logs over INFO because INFO is
filtered out by default; opting users into a log-level change
to see lifecycle events is exactly the friction the issue
complains about.

## Consequences

- Operators of long-running services gain a tick they can trust
  for liveness without configuring a watcher. SIGKILL'd daemons
  no longer hide behind a stale `service.json`.
- Scripts that parse `service status` and only branched on exit
  codes 0/3 now also see code 4 for the divergent case. The
  changelog flags this. Existing 0/3 semantics are preserved.
- The heartbeat write is one I/O every 15 seconds — negligible
  overhead. Atomicity guarantees mean a process killed
  mid-write cannot corrupt the file; the next start sees either
  the prior coherent state or no file.
- `service.lifecycle` log lines change the log volume slightly
  (startup + shutdown per process lifetime). No per-request or
  per-tool spam.
