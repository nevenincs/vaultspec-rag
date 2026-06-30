---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S13'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Split the store client lock into a lifecycle lock plus per-collection point-operation locks, backend-aware so server mode runs lock-free

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Split the single store client RLock into a lifecycle lock (open/close,
  collection create/drop, ensure flags) plus one point-operation lock per
  collection; close() takes all locks in fixed order.
- Server mode (qdrant_url) skips point-operation locking entirely - the
  remote server is concurrency-safe and client-side locking only caps
  throughput.

## Outcome

Vault and code searches no longer serialize against each other; index
upserts on one collection no longer block searches on the other. Baseline
evidence: same-root-mixed dragged 4.2s vault searches to p50 95s purely
via the shared lock.

## Notes
