---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S04'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Unit-test the reorder and each --json outcome shape with an isolated temp status dir

## Scope

- `src/vaultspec_rag/tests/test_cli_server_start.py`

## Description

- Added tests to `test_cli_server_start.py`: the `--json` envelope shapes via the helpers (already_running success, machine_owned failure-with-exit, human-mode emits no JSON); and the genuine guards LIVE via the CliRunner with an isolated singleton fixture - a real bound socket yields `port_in_use`, and a real `acquire_machine_lock` in-process yields `machine_owned` (holder pid == our pid).
- Asserted `_existing_service_running()` is `None` with an isolated empty status dir (the reorder's fall-through).

## Outcome

12 server-start tests pass. The JSON contract and the genuine guard outcomes are covered with no mocks (a real socket, a real machine lock); basedpyright and ruff clean.

## Notes

The live already_running/started paths need a real serving daemon (integration tier); the helper success-path test plus the existing `_existing_service_running` integration test cover the reorder's success side.
