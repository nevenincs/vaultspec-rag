---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S16'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Add a crash-safe machine-scoped service lock under the managed dir

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Added `machine_lock_path()`, `acquire_machine_lock()`, and `release_machine_lock()` to
  `cli/_process.py`. The lock lives alongside the machine-global managed Qdrant storage (the
  shared hardware), NOT under the per-instance status dir, so it is machine-wide even when
  `VAULTSPEC_RAG_STATUS_DIR` is overridden (the dashboard's project-local case) - while still
  relocatable for tests via `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`.
- Acquisition is an atomic `O_CREAT|O_EXCL` create recording the holder pid; a live foreign
  holder returns `(False, holder_pid)`.

## Outcome

The machine-singleton primitive exists and is verified: acquire returns `(True, our_pid)`,
release removes the lock. `ruff` and `ty` pass.

## Notes

The lock co-locates with the shared Qdrant storage because that is the actual machine
resource the singleton protects; this also makes it test-isolatable. Wiring into `server start`
+ the daemon lifespan is S17. No blockers.
