---
tags:
  - '#plan'
  - '#win-shutdown-log'
date: '2026-05-31'
modified: '2026-05-31'
related:
  - '[[2026-05-31-win-shutdown-log-adr]]'
  - '[[2026-05-31-win-shutdown-log-research]]'
---

# `win-shutdown-log` `windows-only cli append of service.lifecycle shutdown line` plan

Implements gh issue #123. On Windows, `os.kill(SIGTERM)` is
`TerminateProcess`; the daemon's atexit + lifespan finally
never fire, so the `service.lifecycle event=shutdown` log line
is missing on `vaultspec-rag server service stop`. The CLI
parent (which already owns the file unlink on stop) appends
the line itself when `sys.platform == "win32"`.

## Proposed Changes

- New helper `_append_lifecycle_shutdown_log(reason, **kv)` in
  `cli.py` formats and appends a structured shutdown line to
  the rotating service log. Narrow `OSError` catch with
  `logger.debug(..., exc_info=True)` per the no-swallow rule —
  never raises, so the shutdown path always completes.
- `service_stop` calls the helper on `win32` only, right after
  the successful `_status_file().unlink()`.
- 3 new unit tests cover success / OSError-suppression /
  end-to-end via `service_stop`.
- Live smoke (Windows): start service, stop, grep service.log
  for the new line.

## Tasks

### Phase 1 — helper

1. Add `_append_lifecycle_shutdown_log(reason: str, **kv: object) -> None` to `cli.py`, alongside the other status /
   log helpers (around `_log_file`, line ~2178).
1. Format: `f"{datetime.now(UTC).isoformat(timespec='seconds')} WARNING  cli.lifecycle event=shutdown reason={reason} {k=v}\n"`.
1. Append via `path.open("a", encoding="utf-8")`.
1. Wrap the open + write in a try/except OSError; the except
   branch calls `logger.debug("lifecycle log append failed: %s", exc, exc_info=True)`. Comment explains why
   suppression is safe (shutdown must complete).

### Phase 2 — call site

1. In `service_stop`, after `_status_file().unlink(missing_ok= True)` (cli.py:2642), add:

   ```python
   if sys.platform == "win32":
       _append_lifecycle_shutdown_log(
           "cli_terminate",
           pid=pid,
           platform="win32",
       )
   ```

### Phase 3 — tests

1. `tests/test_cli.py` `TestWinShutdownLog`:
   - `test_append_writes_expected_format`: monkeypatch
     `_log_file()` to tmp, call the helper with
     `reason="cli_terminate", pid=123`, assert file contains
     a single line matching the daemon's format.
   - `test_append_oserror_is_suppressed_and_debug_logged`:
     monkeypatch `_log_file()` to a non-existent dir, call
     helper, assert no exception + `caplog.records` contains a
     DEBUG message mentioning "lifecycle log append failed".
   - `test_service_stop_emits_log_on_win32`: monkeypatch
     `sys.platform = "win32"` and `_log_file()` to tmp,
     write a status file pointing at the current process PID,
     monkeypatch `_terminate_pid` to a no-op and
     `_is_pid_alive` to return False; invoke `app server service stop`, assert the tmp log contains the
     `cli.lifecycle event=shutdown reason=cli_terminate` line.

### Phase 4 — smoke

1. On Windows, start service on free port, stop it, grep the
   log for `cli.lifecycle event=shutdown reason=cli_terminate pid=<n> platform=win32`. Confirm one occurrence per stop.

### Phase 5 — commit + push + PR + merge

1. One commit with vault docs + helper + call site + tests in
   the same changeset.
1. PR title `feat(cli): #123 windows-only shutdown log mirror`.
1. Ignore Gemini per standing instruction. Merge after CI green.

## Parallelization

Single-file change. Phases 1-3 sequential within `cli.py`.

## Verification

- ruff + mdformat + vault check schema clean.
- 3 new unit tests pass; full unit suite stays green.
- Smoke confirms the log line lands on Windows. POSIX behaviour
  unchanged (the daemon's own lifecycle finally still runs).

## Out of scope

- Replacing `os.kill(SIGTERM)` with a Windows-native graceful
  shutdown signal that actually triggers uvicorn's lifespan
  finally. The codebase already uses `CTRL_BREAK_EVENT` as the
  first attempt; the fallback `SIGTERM` is what trips
  TerminateProcess. Properly wiring graceful shutdown on
  Windows is a much larger uvicorn-integration change and is
  separately filed-able if the cli.lifecycle mirror proves
  insufficient.
