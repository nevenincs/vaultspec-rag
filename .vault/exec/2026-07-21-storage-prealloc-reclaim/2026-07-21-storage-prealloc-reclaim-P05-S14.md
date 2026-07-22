---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S14'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Document the reconcile contract, the automatic convergence behaviour, and the accepted write-ahead log residue

## Scope

- `docs/storage.md`

## Description

- Add a "Shrinking collections you keep" section to `docs/storage-maintenance.md` covering the cost model, automatic convergence, the non-destructive and idempotent properties, and CLI usage.
- Document the mid-merge inflation and why a waited measurement is the only honest one, and the accepted 32 MiB write-ahead log residue.
- Correct the "Why disk usage grows" section and add the three new metrics to its table.
- Add the three configuration knobs to `docs/configuration.md`.
- Add a full `server storage reconcile` entry and its table-of-contents line to `docs/cli.md`.

## Outcome

The feature is documented across the maintenance, configuration, and CLI references, including the reasoning an operator needs to interpret a `converging` result and the residue that is not reclaimed.

## Notes

No incidents.
