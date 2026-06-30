---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S01'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

- Changed `_existing_service_running` to return `tuple[int, int] | None` (the running pid/port) instead of `bool`, removing the inline `_print_lifecycle_lines` so one detection path serves both human and JSON output.
- Updated the two integration assertions in `test_daemon_survives_shell_exit.py` from `is False` to `is None` for the new contract.

## Outcome

Detection is now a pure return; the caller renders the human "already running" lines or the JSON envelope. The dead-status-file cleanup (issue #204) is unchanged.

## Notes

The only production caller is `service_start`; the integration test exercises the live detection path.
