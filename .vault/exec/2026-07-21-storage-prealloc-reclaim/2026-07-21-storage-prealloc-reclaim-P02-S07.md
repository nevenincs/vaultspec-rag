---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:5715a95d3c19d308f7e7c9889412f82b78a0eeab71431c7b0dc69a98fef10b4a'
step_id: 'S07'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Emit reconcile counters, the drifted-collection gauge, and completion-only log lines from the maintenance tick

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`

## Description

- Wire the reconcile policy knobs into the maintenance tick in `src/vaultspec_rag/server/_lifecycle.py`.
- Emit the `maintenance_reconciled_total` and `maintenance_reconciled_bytes_total` counters and the `store_drifted_namespaces` gauge.
- Add reconcile counts to the job summary and the structured cycle log line.
- Add a per-collection `reconciled` log event emitted on completion only.

## Outcome

Reconciliation is observable from metrics, the job summary, and the structured logs without reading the collection configs directly. The per-collection event fires only on completion, so a mid-flight collection never produces a log line implying a finished convergence.

## Notes

No incidents.
