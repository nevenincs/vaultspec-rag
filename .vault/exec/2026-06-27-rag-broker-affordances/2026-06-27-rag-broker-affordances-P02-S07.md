---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S07'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir

## Scope

- `src/vaultspec_rag/tests/test_machine_discovery.py`

## Description

- Authored `test_machine_discovery.py` (unit, isolated singleton paths): the pointer sits beside the lock and is named `service.json`; `read_machine_discovery` is `None` when absent; a write/read round-trips the payload; the reader tolerates garbage and a non-object JSON array as `None`; and `_unlink_status_file_silently` removes the pointer.

## Outcome

5 discovery tests pass with no mocks (real files at a temp-isolated machine-global path); basedpyright and ruff clean.

## Notes

Tests both `_machine_lock` (path + reader) and the daemon `_lifecycle` write/cleanup directly, so the contract is covered without standing up a full daemon.
