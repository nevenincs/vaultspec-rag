---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S11'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Assert the attribution fields appear in the shutdown log line and the stop --json envelopes across the stop exit paths

## Scope

- `src/vaultspec_rag/tests/test_cli_server_stop.py`

## Description

- Added a `TestShutdownAttribution` class: a shape test for `_initiator_fields`
  (pid equals the running process, bounded non-empty argv containing python or
  pytest, cwd is a real directory equal to the current one).
- Asserted through the real `_stop_success` helper that the initiator fields
  land in the `stopped` `--json` envelope `data`.
- Extended the existing `cleaned` outcome test to assert the initiator fields
  are absent, since that path terminates nothing.
- Added a live audit-line test that terminates a real non-python child
  (`cmd.exe ping` on win32 spawned in a new process group so CTRL_BREAK cannot
  reach the test runner, `sleep` on POSIX) under an isolated status dir and
  reads the isolated shutdown log, asserting the `cli_terminate` line carries
  `initiator_pid`, `initiator_cmd`, and `initiator_cwd`.

## Outcome

The full `test_cli_server_stop.py` plus `test_service_stop_port.py` run green
(17 passed). Ruff, ruff format, and basedpyright pass on the test file. No
mocks, patches, or skips.

## Notes

The child in the audit-line test is deliberately non-python and, on Windows,
spawned with `CREATE_NEW_PROCESS_GROUP`: the tokenless identity fallback would
confirm a python child as ours, and a CTRL_BREAK sent to a shared console
process group has previously killed a pytest run. No skipped work.
