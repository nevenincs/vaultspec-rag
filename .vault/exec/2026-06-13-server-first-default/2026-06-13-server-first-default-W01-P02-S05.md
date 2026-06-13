---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S05'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# make service_lifespan select server mode by default and use the local store only when local-only is set, reading effective server mode from config

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Switched the server-mode startup gate in `service_lifespan` from reading the raw `cfg.qdrant_server` flag to calling `cfg.effective_server_mode()`, the resolution added in the prior phase that returns `qdrant_server and not local_only`.
- Reworded the startup comment to state that server mode is the default backend and that selection now honours the `--local-only` escape hatch, which deterministically routes to the per-project on-disk store.

## Outcome

The resident service now starts in server mode by default and selects the local on-disk store only when `local_only` is set, exactly as the server-first decision requires. Because the selection goes through `effective_server_mode()`, the `--local-only` opt-out always wins over the server default at the one place that decides whether to spawn the supervised child. The operator-set `QDRANT_URL` remote escape hatch is preserved unchanged. `ruff check` and `basedpyright` on the changed file are clean.

## Notes

No incidents. The change is a single call-site substitution; the downstream supervision, watcher wiring, and shutdown ordering are unaffected because they already keyed off the spawn having happened, not off the flag.
