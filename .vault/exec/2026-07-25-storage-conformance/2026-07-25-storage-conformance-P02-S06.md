---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:3297b492a636dc06e8cc429eb2b849ff993cd7c6ee3e8dd7f485b38c2c0e51d7'
step_id: 'S06'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Read live collection geometry back from the backend behind the existing per-collection ensure cache so it never reaches the query path

## Scope

- `src/vaultspec_rag/store.py`

## Description

Plan evidence: `2026-07-25-storage-conformance-plan` marks `P02.S06` closed for Read live collection geometry back from the backend behind the existing per-collection ensure cache so it never reaches the query path.

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

Template evidence: intro_commit=1c1b0441e97f7423e71cd4e4fc0e3096126888bb; template_commit=1c1b0441e97f7423e71cd4e4fc0e3096126888bb:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
