---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S06'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# Assert the stop --json envelope and exit code on each exit path alongside the existing start --json matrix

## Scope

- `src/vaultspec_rag/tests/integration`

## Description

- Add `src/vaultspec_rag/tests/test_cli_server_stop.py` mirroring the start
  matrix: envelope-shape tests for every success status (`stopped`,
  `already_stopped`, `cleaned`, `reclaimed`), the human-mode no-JSON
  guarantee, and the `identity_unconfirmed` failure shape with exit 1.
- Add live CLI-wiring tests against isolated singleton paths: nothing to
  stop (default and `--port` variants) is `already_stopped` exit 0; a dead
  recorded pid is `cleaned` exit 0; a live unconfirmed pid is
  `identity_unconfirmed` exit 1 in both `--json` and human modes.

## Outcome

11 tests, all passing, alongside the existing start `--json` matrix and the
untouched stop-port / singleton-reclaim suites. The stopped/reclaimed CLI
paths against a real daemon remain covered by the existing integration
lifecycle tests; their envelope shapes are pinned at the helper tier here.

## Notes

First staging attempt used a sleeping python child for the unconfirmed-pid
case; the discovery file carries no token, so identity fell back to the
executable-name check, confirmed the python child as ours, and the resulting
terminate sent CTRL_BREAK to the shared Windows process group - killing the
pytest run itself. The test now spawns a non-python child (`cmd.exe` ping on
Windows, `sleep` on POSIX) and documents why.
