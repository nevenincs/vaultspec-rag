---
tags:
  - '#research'
  - '#service-lifecycle'
date: '2026-05-30'
related: []
---

# `service-lifecycle` research: `daemon-side service.json lifecycle audit`

## Trigger

Issue #113 collects three coupled gaps in the daemon lifecycle:

- The HTTP service daemon never writes or unlinks `service.json`;
  only the CLI parent does, so SIGKILL / OOM / startup exception
  leave the file with a stale PID + port.
- `service status` consults the sources of truth in series and
  silently picks one over another, so divergences (PID alive but
  port not listening, etc.) get hidden behind a misleading row.
- `service.log` has no structured lifecycle entries
  distinguishing intentional stop from process disappearance.

PR #109's Wave 1F-9 plan flagged all three as Wave 2 work and the
user has now scheduled them as the next sequential rollout. This
research grounds the implementation before the ADR.

## Method

One grounding pass over the worktree (Sonnet agent) covering five
audit areas: service.json lifecycle today, `service status` today,
`service.log` today, atexit/signal patterns elsewhere, heartbeat
design constraints.

## Findings

### service.json lifecycle today

- All read/write/unlink happens in `cli.py`:
  `_status_file()` (L1777), `_write_service_status` (L1800),
  `_read_service_status` (L1819). Unlinks: L2106 (start guard),
  L2124 (start failure), L2186 (stop stale), L2204 (stop normal),
  L2241 (status stale).
- `_write_service_status` writes atomically (`.tmp` + `os.replace`)
  with schema `{"pid": int, "port": int, "started_at": str}`
  (L1808-1811).
- `mcp_server.py` has **zero references** to the status file. The
  daemon process never touches it. The separation is implicit; no
  comment explains the ownership boundary.
- `service_lifespan` in `mcp_server.py` (L141-188) has no
  `atexit.register`, no `signal.signal`, no `try/finally` that
  touches a status file. Its only shutdown behaviour is
  `_stop_all_watchers()` -> `_registry.close_all()` ->
  `logger.info("Service shutdown complete")` (L183-188).

### `service status` today

- `handle_service_status` (L2214-2265) consults sources in
  sequence:
  1. `_read_service_status()` -> None: print "stopped", return.
  1. `_is_our_service(pid)` -> False: unlink + print
     "stale PID cleaned", return.
  1. Print `State: running` unconditionally (L2246) before any
     network probe.
  1. `_health_probe(port)` -> None: print Health: unreachable.
- The gap: step 3 commits to "running" before step 4 has data.
  Divergence (PID alive, port not listening) reads as
  `running / unreachable` with no explicit divergence flag.
- `_is_pid_alive` (L1839): solid (Windows: `OpenProcess` +
  `GetExitCodeProcess`; Unix: `os.kill(pid, 0)`).
- `_is_our_service` (L1878): checks executable name only
  (`"python" in path.lower()` or `/proc/{pid}/cmdline` contains
  `"vaultspec_rag"`). **PID reuse false-positive risk**: any
  Python process at the recycled PID passes on Windows. On Unix
  the cmdline test is tighter but still falls back to `True` on
  procfs failure.
- `_health_probe` (L1958): HTTP GET `/health` with 5s timeout.
  Does not verify that the responding process is the one in
  `service.json` — any service on the port answers.

### `service.log` today

- `install_daemon_log_rotation` (`logging_config.py` L244) writes
  via `DaemonRotatingFileHandler`, format
  `%(asctime)s %(levelname)-8s %(name)s: %(message)s`.
- Startup log lines in `service_lifespan` (L164-174): all
  `logger.info` (`HF cache`, `All models loaded`, `Service startup complete`).
- Shutdown log line at L188: `logger.info("Service shutdown complete")`.
- **Default log level is WARNING** (`VAULTSPEC_RAG_LOG_LEVEL`,
  `logging_config.py` L56). So every existing lifecycle INFO
  line is **silent by default** unless the user opts in. The
  primary visibility gap.

### Atexit / signal patterns elsewhere

`grep` confirms zero `atexit.register` and zero
`signal.signal`/`signal.SIGTERM` registrations anywhere in
`src/`. The only signal references are the CLI _sending_ SIGTERM
to the daemon (`os.kill(pid, signal.SIGTERM)` at `cli.py` L2039
and L2045). Both atexit and signal handlers need to be introduced
fresh in `mcp_server.py`; no pre-existing convention to mirror.

### Heartbeat design constraints

- `service.json` is pure JSON, parsed via
  `json.loads(sf.read_text())`. Adding `"last_heartbeat": str`
  (ISO-8601 UTC) round-trips cleanly; `_read_service_status` only
  validates `pid`/`port`, so new fields are transparent.
- Background-task pattern already in `mcp_server.py`:
  `asyncio.create_task(watch_and_reindex(...))` at L268 inside
  `_start_watcher()`. Heartbeat should follow the same shape —
  an `asyncio.create_task` launched inside `service_lifespan`
  before `yield`, cancelled in the `finally` block alongside
  `_stop_all_watchers()`.
- File I/O wrapped in `asyncio.to_thread` to avoid blocking the
  event loop, with the same atomic write pattern as
  `_write_service_status` (`.tmp` + `os.replace`).

### Staleness threshold

Watcher cooldown elsewhere is 30s. Recommend a **15s heartbeat
interval** with a **60s staleness threshold** — four beats per
minute tolerates up to three missed beats before a "dead"
verdict, robust to transient I/O stalls or load spikes without
masking real crashes. Anything tighter risks false positives on
loaded systems; anything looser defeats the purpose for a
human-triggered `status` command expecting near-real-time truth.

## Recommendation

- Heartbeat as an async task launched inside `service_lifespan`,
  same shape as the existing watcher task, cancelled in `finally`.
- `atexit.register` + SIGTERM handler in the daemon entry that
  unlink `service.json` on clean exit. CLI keeps its existing
  ownership for start; the daemon now owns end-of-life cleanup.
- `service.lifecycle` log entries at WARNING level (above the
  default LOG_LEVEL threshold) so they're visible without opting
  in. Structured key=value format for greppability: `event=startup pid=... port=...`, `event=shutdown reason=clean|signal|atexit`.
- `service status` consults all four sources unconditionally
  before rendering, then surfaces each as its own row and adds an
  explicit `Divergence` row when signals conflict. Heartbeat
  freshness gets its own row sourced from the new field.
