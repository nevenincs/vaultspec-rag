---
tags:
  - '#exec'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S06'
related:
  - "[[2026-07-25-index-resume-drift-race-plan]]"
---

# Extract drift ownership into its own collaborator that holds the drop-points-then-remove-units ordering as a property of the type

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Extract drift ownership into its own module holding detection, the point
  drop, and the unit removal as one operation with one order.
- Give the owner the per-path retry budget and the deferred set, because
  giving up on a path is the same decision as noticing it drifted.
- Reduce the indexer's pre-dispatch sweep to a delegation.
- Hold the owner as run state so one generation sees one owner.

## Outcome

The drop-points-then-remove-units ordering used to live in a docstring on the
indexer's sweep method and was enforced by nothing. It is now the body of one
method on one type, and there is no way to reach either half separately: the
storage delete and the ledger re-open are consecutive statements a caller
cannot interleave or reorder.

The extraction also fixed a latent defect the docstring could not have caught.
The old sweep dropped every point storage reported for the path. That is
correct before dispatch, when nothing new has been written, and wrong at any
later moment, because the incoming content reaches storage before the ledger
accepts it. The owner takes the identities the pending mutation claims and
excludes them, which makes the same operation safe at both moments and is why
one type can serve both.

Drift volume is tallied on the owner - paths superseded, supersede operations,
paths deferred - as immutable state a reporting surface can read. Nothing
consumes it yet; the counter's home exists, its wiring into job state does
not, and that remains open.

Gates on the new module: lint clean, format clean, type check reports no
diagnostics.

## Notes

The owner touches no GPU path, holds no lock, and owns no queue. It runs on
the consumer thread that already exists and on the coordinator, so the single
in-process consumer constraint is untouched: this seam is an ownership
boundary, not a concurrency one.

The remaining collaborators this Phase scopes - chunk production and
submission, generation and ledger lifecycle, and the duplicated stat-failure
classification - were not extracted. Drift ownership was taken first because
the fix cannot be stated without it, and the others carry no such dependency.
