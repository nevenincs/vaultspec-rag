---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Add the storage reconcile verb with preview, collection bound, and no-wait mode, emitting exactly one structured envelope per exit path

## Scope

- `src/vaultspec_rag/cli/_service_storage.py`

## Description

- Add the `server storage reconcile` verb and `_render_reconcile` to `src/vaultspec_rag/cli/_service_storage.py`, with the `server.storage.reconcile` command constant.
- Support `--dry-run`, `--yes`, `--limit`, `--wait/--no-wait`, and `--json`.
- Follow the existing `_run_storage_op`, `_require_yes_for_json`, and `_emit_json` idiom, emitting exactly one structured envelope per exit path.
- Report a backend with no drift as `already_converged` at exit 0.

## Outcome

Operators can preview and drive convergence on demand. The verb honours the broker-facing contract: one envelope on every exit path, and an already-satisfied request is a success rather than a fault.

## Notes

No incidents.
