---
tags:
  - '#exec'
  - '#index-gpu-pipeline'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S02'
related:
  - "[[2026-06-02-index-gpu-pipeline-plan]]"
---

# Shut the consumer down with a sentinel and re-raise any consumer-thread exception in the main thread, and move stale-purge and metadata accounting after the join

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Shut the consumer down with a `None` sentinel; capture any consumer-thread exception and re-raise it in the main thread after join.
- Move stale-purge and metadata accounting to after the consumer join so they observe the full upserted set.

## Outcome

Consumer-side failures (GPU OOM, Qdrant error) surface in the caller instead of hanging.

## Notes

Code review found a hang vector (unguarded sentinel put + unbounded join under the writer lock). Fixed in a follow-up: liveness-guarded timed put + deadline-bounded join that escalates to a raise.
