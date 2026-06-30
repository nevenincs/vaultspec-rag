---
tags:
  - '#exec'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
step_id: 'S05'
related:
  - "[[2026-06-27-rag-broker-affordances-plan]]"
---

# Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module

## Scope

- `src/vaultspec_rag/_machine_lock.py`

## Description

- Added `machine_discovery_path()` (= `machine_lock_path().parent / "service.json"`, STATUS_DIR-independent, distinct from the per-STATUS_DIR file) and a tolerant `read_machine_discovery()` to `_machine_lock.py`, both exported in `__all__`.

## Outcome

The machine-global discovery pointer has a canonical path beside the lock and a reader that treats a missing/unreadable/non-object file as truthful absence (never raising), so a consumer finds the one service regardless of its own STATUS_DIR.

## Notes

Placed in `_machine_lock.py` (the existing machine-global-path owner) so it stays a neutral leaf the daemon and a consumer share.
