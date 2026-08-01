---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:9f988db42276218177a22c756cb7fac772642598ee154529f266319e9e363fd3'
step_id: 'S13'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Clamp bounded write retry and sleep to the remaining durable no-progress budget

## Scope

- `src/vaultspec_rag/_store_writes.py`
- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/indexer/_streaming.py`
- Store write-path regression tests and explicit direct-caller updates.

## Description

- Replace hard-coded retry attempts and delays with validated configuration.
- Admit each Qdrant upsert with a timeout no greater than the caller's remaining durable no-progress budget.
- Route retry waits through a limited caller-owned policy capability and clamp every wait to the sampled remainder.
- Require every store upsert caller to select a managed write policy or explicitly identify a direct unbounded call.
- Preserve original storage exceptions on unrecoverable failure and retry exhaustion while returning the typed no-progress outcome on budget expiry.

## Outcome

Store writes can no longer start a request or retry wait beyond the durable
no-progress budget supplied by a managed indexing run. The store consumes only
the remaining-time and interruptible-wait capabilities; it cannot own or reset
the run clock. Direct callers pass `None` explicitly, with no legacy signature
or compatibility wrapper retained.

The focused real-behavior suite passed 61 tests, including a local-Qdrant test
that proves an expired production write policy prevents point mutation. Ruff
and strict type checks passed. Independent review found no remaining critical
or high issue.

## Notes

Durable clock construction and producer/consumer polling remain owned by the
next approved run-policy step. No service, Qdrant process, or unrelated live
GPU workload was started, stopped, or restarted.
