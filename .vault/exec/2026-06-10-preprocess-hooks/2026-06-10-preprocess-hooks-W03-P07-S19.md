---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S19'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Implement upsert, stored-chunk id, and purge-by-source-path reconciliation for preproc units (D12)

## Scope

- `src/vaultspec_rag/store.py`

## Description

Upsert reuses the existing `upsert_code_chunks` (now writing the six new payload fields),
so embedding and stale-chunk reconciliation are unchanged. Preproc stored-chunk ids use the
`{rel_path}::pp:{index}:{blake2b6}` scheme (built in the worker's `_chunks_from_output`),
unique per unit. Purge-by-source-path is the existing `get_code_ids_by_paths` /
modified-file reconciliation, since a preproc chunk's `path` is the source rel path (D12).

## Outcome

Re-index of a preprocessed source replaces its chunks by path exactly like code files; no
new purge path needed.

## Notes

Reusing the code path is the point of the S18 storage decision - one upsert/reconcile seam.
