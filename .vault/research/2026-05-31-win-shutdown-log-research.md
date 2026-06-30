---
tags:
  - '#research'
  - '#win-shutdown-log'
date: '2026-05-31'
modified: '2026-06-30'
related: []
---

# `win-shutdown-log` research: `daemon shutdown log absent on windows — terminateprocess audit`

## Trigger

Known limitation documented in #113's ADR and surfaced during
Wave 1F's honest audit. On Windows, `os.kill(pid, signal.SIGTERM)`
is `TerminateProcess` — the daemon's `atexit` handler and
lifespan `finally` block **never run** on `vaultspec-rag server service stop`. The CLI parent unlinks `service.json` itself
(file lifecycle stays correct), but the structured
`service.lifecycle event=shutdown reason=clean` log line **never
lands in `service.log`** on Windows. Filed as gh issue #123.

## Method

Code read against the just-merged main (after PR #131 / #126).

## Findings

### Termination path on Windows

`cli._terminate_pid(pid)` (`cli.py:2461`):

- On `sys.platform == "win32"`: `os.kill(pid, signal.CTRL_BREAK_EVENT)`
  first (graceful), waits 2 s, falls back to
  `os.kill(pid, signal.SIGTERM)` if the process is still alive.
- On POSIX: `SIGTERM` first, `SIGKILL` fallback.

On Windows, even the graceful `CTRL_BREAK_EVENT` does not
reliably trigger uvicorn's clean-shutdown path under
`vaultspec-rag server service start` (foreground daemon). The
fall-through `SIGTERM` then becomes `TerminateProcess` — the
process dies without running atexit handlers.

POSIX is fine: uvicorn's signal handler routes SIGTERM through
clean shutdown which triggers `service_lifespan`'s `finally`
block, which calls `_record_shutdown("clean")`, which logs
`service.lifecycle event=shutdown reason=clean` at WARNING.

### CLI's existing stop flow

`cli.service_stop()` (`cli.py:2602-2649`):

1. Reads `service.json` via `_read_service_status()`.
1. Validates PID via `_is_our_service(pid)` — bails out if dead
   or unrelated.
1. Calls `_terminate_pid(pid)`.
1. Polls `_is_pid_alive(pid)` for up to 5 s.
1. Unlinks `service.json` via `_status_file().unlink(missing_ok= True)`.
1. Prints the green "Service stopped" panel.

The CLI parent already owns the file lifecycle on stop (line
2642). The gap is only the log line.

### Log file path resolution

`cli._log_file()` (`cli.py:2178-2189`) returns
`_status_dir() / cfg.log_file`, the same path
`DaemonRotatingFileHandler` writes to from
`mcp_server._resolve_log_path()` (single source of truth via
`get_config().log_file`). Appending from the CLI process lands
in the same rotating file the daemon was writing to.

### Daemon's `_lifecycle_log` format

`mcp_server._lifecycle_log(event, **kv)` (`mcp_server.py:167-181`):

```
WARNING service.lifecycle event=<event> <key=value> <key=value>
```

The DaemonRotatingFileHandler prepends a `%(asctime)s` and
formats as `{ts} WARNING service.lifecycle ...`. The CLI must
emit the same shape so grep / log-aggregation queries work
across both daemon-emitted and CLI-emitted shutdown lines.

### Why not invoke the daemon's helper?

The CLI cannot call `mcp_server._lifecycle_log` because importing
`mcp_server` from CLI startup time pulls in FastMCP, Pydantic
models, the registry — heavy deps that the CLI's `service_stop`
command avoids by design (start-up speed). A local CLI helper
that writes the same string format is the lighter touch.

## Recommendation

Add `_append_shutdown_log(reason: str, **kv: object)` to `cli.py`
that:

1. Formats the line as the daemon's helper does:
   `{utcnow().isoformat()} WARNING service.lifecycle event=shutdown reason={reason} {extra k=v}`.
1. Appends to `_log_file()` with `encoding="utf-8"`.
1. Catches `OSError` narrowly (log file missing / permission) and
   emits a `logger.debug(..., exc_info=True)` line — per the
   no-swallow rule. Never raises; shutdown must complete even if
   the log append fails.

Call it from `service_stop` only on `sys.platform == "win32"`,
immediately after the successful unlink at `cli.py:2642`.
Mention `pid=<n>` and `platform=win32` in the kv block so the
line is self-identifying.

POSIX path is unchanged: the daemon's own `_record_shutdown ("clean")` continues to land via the lifespan finally.

## Exception-handling note

Per `[[feedback_no_adhoc_no_swallow]]`, the new helper's
`OSError` catch is narrow (specific exception type), logs the
exception with `exc_info=True`, and is gated by a comment
explaining why the suppression is safe (shutdown must complete
even if the log file is missing). No bare `except` clauses
introduced.
