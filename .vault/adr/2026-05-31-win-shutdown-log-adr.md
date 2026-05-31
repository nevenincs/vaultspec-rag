---
tags:
  - '#adr'
  - '#win-shutdown-log'
date: '2026-05-31'
related:
  - '[[2026-05-31-win-shutdown-log-research]]'
---

# `win-shutdown-log` adr: `cli-side shutdown lifecycle log mirror on win32` | (**status:** `accepted`)

## Problem Statement

On Windows, `os.kill(pid, signal.SIGTERM)` is `TerminateProcess`.
The daemon's `atexit` and lifespan `finally` block never run on
`vaultspec-rag server service stop`. The CLI parent unlinks
`service.json` correctly, but the structured
`service.lifecycle event=shutdown reason=clean` log line never
lands in `service.log`. Post-mortem on Windows reads "the log
went quiet" — the exact failure mode #113 set out to close.

POSIX is unaffected: uvicorn's SIGTERM handler routes through
clean shutdown which fires the lifespan finally and logs the
shutdown line.

## Considerations

- The CLI parent already owns the file lifecycle on stop (line
  2642 unlinks `service.json`). Adding a log append there is
  the natural extension.
- Importing `mcp_server` from CLI startup pulls in FastMCP +
  registry + heavy deps. The CLI must format the log line
  locally rather than call `mcp_server._lifecycle_log`.
- The format must match the daemon's so grep / log-aggregation
  queries are uniform across both code paths.
- The append must never raise — `service_stop` must complete
  even if the log file is missing or unwritable. The no-swallow
  rule still requires a `logger.debug` line in the failure path
  so the suppression is observable.

## Constraints

- Windows-only. POSIX continues to use the daemon's existing
  `_record_shutdown("clean")` via the lifespan finally.
- No new dependencies. Pure stdlib (`pathlib`, `datetime`,
  `logging`).
- The reason field on the new CLI-emitted line is
  `cli_terminate` (not `clean`) so log analysis can distinguish
  CLI-mediated terminations from daemon-self-reported clean
  shutdowns.

## Implementation

### Helper (`src/vaultspec_rag/cli.py`)

```python
def _append_lifecycle_shutdown_log(reason: str, **kv: object) -> None:
    """Append a service.lifecycle shutdown line to the rotating log.

    Used on Windows only — the daemon's atexit handler does not
    fire under TerminateProcess, so the CLI parent emits a
    mirror line itself after a successful stop. Matches the
    daemon-side _lifecycle_log format so grep queries cover
    both code paths.

    Never raises: shutdown must complete even if the log file
    is missing or unwritable. Failures are logged at debug.
    """
    path = _log_file()
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    parts = [f"event=shutdown", f"reason={reason}"]
    parts.extend(f"{k}={v}" for k, v in kv.items())
    line = f"{ts} WARNING  cli.lifecycle {' '.join(parts)}\n"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        # Log-append failures must never block the shutdown
        # path. Per the no-swallow rule, debug-log the failure
        # so it is observable.
        logger.debug("lifecycle log append failed: %s", exc, exc_info=True)
```

Note: logger name is `cli.lifecycle` (not the daemon's
`service.lifecycle`) so log readers can tell at-a-glance that
the entry was emitted by the CLI parent after a Windows-only
TerminateProcess path. Both subscribe to the
`service.lifecycle*` grep prefix.

### Call site (`src/vaultspec_rag/cli.py`)

In `service_stop()`, right after the existing
`_status_file().unlink(missing_ok=True)` (line 2642):

```python
if sys.platform == "win32":
    _append_lifecycle_shutdown_log("cli_terminate", pid=pid, platform="win32")
```

### Tests

- Unit test: monkeypatch `_log_file()` to return a tmp path,
  call `_append_lifecycle_shutdown_log("cli_terminate", pid=123)`, assert the file contains exactly one line matching
  `r"^\d{4}-.* WARNING  cli\.lifecycle event=shutdown reason=cli_terminate pid=123$"`.
- Unit test: monkeypatch `_log_file()` to return a path inside
  a non-existent directory, call the helper, assert no
  exception raised and `caplog.records` contains one DEBUG line
  mentioning "lifecycle log append failed".
- Unit test: monkeypatch `sys.platform = "win32"`,
  monkeypatch `_log_file()` to tmp, run `service_stop` against
  a self-PID + injected `_terminate_pid` stub, assert the log
  line is present in the tmp file.

## Rationale

A CLI-side mirror is the smallest cut that closes the Windows
gap without replacing the daemon's signal-handling design.
Earlier #113 deliberately did NOT override SIGTERM/SIGINT on
the daemon because uvicorn owns those signals — overriding
broke flush ordering. On Windows, neither uvicorn nor our hook
can run after TerminateProcess; the parent process is the only
remaining vantage point.

`cli.lifecycle` over `service.lifecycle` as the logger token so
the line is clearly attributable. The `reason=cli_terminate`
field distinguishes from the daemon's `reason=clean`.

## Consequences

- Windows operators get the same log audit trail POSIX
  operators have had since #113. Post-mortem no longer reads
  "the log went quiet".
- One extra disk write per `service stop` on Windows.
  Negligible.
- POSIX behaviour unchanged — the conditional `if sys.platform == "win32"` gate ensures no double-logging on
  Linux/macOS where the daemon's own lifecycle finally fires.
- A noisy or rotating log won't lose the line: the append
  happens before the rotation can fire (atomic single-line
  write), and Windows' file locking model allows append-mode
  writes from a non-owning process.
