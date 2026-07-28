---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
step_id: 'S05'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Preserve unscoped_required in record_interrupted and record_success instead of forcing escalation, keeping failure, recovery, load, and refresh promotion unchanged

## Scope

- `src/vaultspec_rag/watcher_retry.py`

## Description

- `record_interrupted` preserves `unscoped_required` instead of forcing it: a live interruption keeps its exact dirty paths in the convergence slot.
- `record_success` clears `unscoped_required` unless a newer pending generation already required it; a generation marked mid-attempt by the live instance stays scoped.
- Failure, crash recovery, construction over a loaded pending bit, and scope refresh keep escalating unchanged.

## Outcome

Coalesced admissions, operator cancels, and mid-attempt events converge scoped in the live process; every process-boundary path still promotes to unscoped.

## Notes

A prior escalation deliberately survives a success that leaves a newer generation pending; clearing it there would be correct but was kept conservative.
