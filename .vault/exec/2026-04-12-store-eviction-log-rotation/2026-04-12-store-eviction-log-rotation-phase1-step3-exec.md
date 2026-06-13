---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-3

## goal

Introduce `DaemonRotatingFileHandler` and `install_daemon_log_rotation`
helper in `logging_config.py` per ADR D1. Add unit-level coverage for
the re-`dup2` invariant and idempotent installation.

## files touched

- `src/vaultspec_rag/logging_config.py`
- `src/vaultspec_rag/tests/test_logging_config.py` (new)

## what was done

- Added `DaemonRotatingFileHandler` subclass with `@override`
  `doRollover` that (a) redirects fds 1 and 2 to `os.devnull` before
  calling `super().doRollover()`, (b) runs the parent rotation, and
  (c) re-`dup2`s fds 1 and 2 onto the freshly opened stream. Wrapped
  in `self.acquire()` / `self.release()` (the handler's RLock)
  and a best-effort `logger.exception` + re-raise on failure.
- Added `install_daemon_log_rotation(log_path, *, max_bytes, backup_count)` returning a `DaemonRotatingFileHandler`. Idempotent
  via root-logger scan; sets a formatter, attaches to root, performs
  the initial `os.dup2` of fds 1/2 onto the new stream.
- Wrote two real-unit tests using `tmp_path` and genuine
  `os.dup`/`os.dup2` fd save-and-restore (no mocks).

## deviations from plan

- The ADR D1 pseudocode did not mention redirecting fds 1/2 to
  `os.devnull` before the rename. On Windows the dup2'd fds pin
  the file open, so `os.rename` fails with `PermissionError`. This
  is the documented Windows FD-dup gotcha; the fix is implemented
  directly in `doRollover`. ADR D1's acceptance of the "microsecond
  window between doRollover and re-dup2" for raw C-level writes is
  still honored — during the rename, raw fd-1/2 writes go to
  `os.devnull` and are lost, not misdirected. This is strictly
  safer than pinning the rename open.

## test results

- `pytest src/vaultspec_rag/tests/test_logging_config.py -x -v` ->
  2 passed.
- `ruff check` + `ty check` clean on the two modified files.

## commit hash

`32d87f1 feat(logging): add DaemonRotatingFileHandler with FD re-dup2`

## time spent

~20 minutes (Windows rename collision added one debug cycle).
