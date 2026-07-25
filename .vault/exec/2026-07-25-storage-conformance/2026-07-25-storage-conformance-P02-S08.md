---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S08'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Refuse a dense width, distance, or vector-name disagreement at the ensure step with a message naming expected and actual

## Scope

- `src/vaultspec_rag/store.py`

## Description

## Outcome

`StorageGeometryError`, raised from `_verify_conformance` on and only on
`geometry_fatal`, naming both the expected and the actual width.

This moves a failure that was already fatal, not a new one. Previously the
disagreement surfaced at the upsert, where the write classifier does not treat
the rejection as unrecoverable, so the run spent its full retry and backoff
budget logging a transient store failure before raising; on the search side the
first line an operator saw blamed hybrid search while the dense fallback raised
uncaught. Refusing at ensure returns that budget and attributes the cause.

Because the raise happens before `_ensured` is set, a subsequent call re-probes
rather than caching a fatal - a store that is repaired underneath recovers
without a reopen.

## Notes
