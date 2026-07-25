---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S06'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Read live collection geometry back from the backend behind the existing per-collection ensure cache so it never reaches the query path

## Scope

- `src/vaultspec_rag/store.py`

## Description

## Outcome

`_live_dense_dim` reads the collection back and returns the dense width, or
`None` when the probe cannot be answered - an unnamed vector shape, or any
backend error. `None` yields `unverifiable` rather than an exception, because a
backend that cannot answer a configuration question must not take down a store
open.

Placed behind the existing `_ensured` marker inside `_ensure_table`, so the read
happens once per collection per store instance and never on the query path. That
is the same cache the payload-index reconcile already sits behind, whose measured
cost is documented at that site.

## Notes
