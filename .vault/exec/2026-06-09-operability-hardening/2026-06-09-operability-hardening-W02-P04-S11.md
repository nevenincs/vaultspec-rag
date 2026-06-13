---
tags:
  - '#exec'
  - '#operability-hardening'
date: '2026-06-09'
modified: '2026-06-09'
step_id: 'S11'
related:
  - '[[2026-06-09-operability-hardening-plan]]'
---

# Spawn the daemon with Windows Job-Object breakaway and an OSError fallback

## Scope

- `src/vaultspec_rag/cli/_process.py`
- `src/vaultspec_rag/tests/test_process.py`

## Description

- Added three named constants below `_resolve_daemon_interpreter` in `_process.py`:
  `_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200`, `_WIN_CREATE_NO_WINDOW = 0x08000000`,
  and `_WIN_CREATE_BREAKAWAY_FROM_JOB = 0x01000000`. Constants replace the inline hex
  literals that existed before and provide a stable import surface for tests.
- Modified the Windows branch of `_spawn_service` to attempt `Popen` with
  `_WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW | _WIN_CREATE_BREAKAWAY_FROM_JOB`.
  On `OSError` (restricted Job Object denies breakaway — common in terminal emulators,
  CI runners, and VS Code integrated terminal) the function logs a `WARNING` and retries
  with only `_WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW`, which is the
  pre-fix behaviour. The fallback is no worse than before; it is strictly an
  improvement on the success path.
- Non-Windows spawning (`start_new_session=True`) is unchanged.
- Added `TestWindowsCreationFlags` class to `test_process.py` (five `unit`-marked tests):
  - `test_create_new_process_group_value` — asserts `0x00000200`
  - `test_create_no_window_value` — asserts `0x08000000`
  - `test_create_breakaway_from_job_value` — asserts `0x01000000`
  - `test_breakaway_flag_included_in_full_creationflags` — asserts the combined flags
    include the breakaway bit
  - `test_fallback_flags_exclude_breakaway` — asserts the fallback combination omits it

## Outcome

`ruff check` and `ty check` both clean on the two modified files.
8 unit tests pass (5 new flag tests + 3 pre-existing interpreter tests).

## Notes

`CREATE_BREAKAWAY_FROM_JOB` is `0x01000000` per the Windows API (MSDN
`CreateProcess` dwCreationFlags). The flag causes the new process to detach from
the launching shell's Job Object, so the daemon is not killed when that shell exits
(the root cause of the Qdrant `exclusive.lock` deadlock described in #166).
The OSError catch is broad rather than `PermissionError`-only because the Windows
kernel returns `ERROR_ACCESS_DENIED` (mapped to `PermissionError`) for policy
denial but may return other Win32 error codes in edge configurations; catching
`OSError` (the base class) is the safe choice. The warning is always emitted so
the fallback is observable in the service log.
