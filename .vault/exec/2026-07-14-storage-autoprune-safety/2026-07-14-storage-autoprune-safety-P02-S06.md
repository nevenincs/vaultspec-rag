---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:bf913ab8b26c02d9ba5df0e7649441cfcd21b2fa81d0ee506dc58f628daa0980'
step_id: 'S06'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Start and cancel the maintenance task in the daemon lifespan, delayed one interval after startup and gated on server mode plus the storage_autoprune knob

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Generalize the lifespan's single heartbeat task handoff to a list of
  periodic tasks; `_shutdown_components` cancels and awaits each in order.
- Create the maintenance task at startup only when
  `effective_server_mode()` and the `storage_autoprune` knob are both on
  (the tick re-checks both cheaply, so a config flip is honoured either
  way); the loop itself delays the first cycle one full interval.

## Outcome

Server + machine-lock lifespan suites pass (121 tests); ruff, ruff
format, and basedpyright clean.

## Notes

None.
