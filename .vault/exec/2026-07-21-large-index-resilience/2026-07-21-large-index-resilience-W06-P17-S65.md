---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:fa4cf0d473ab9162b6368125e7fddb5b4de1e7608a01e723fce848d406ca64c9'
step_id: 'S65'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Retry a contended ledger transaction under a bounded policy instead of failing the generation and discarding storage-confirmed work

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`

## Description

- Add a bounded contention replay helper with short backoff beside the transaction helper.
- Apply it to the storage-confirmed unit recording path.
- Split that method so the replay has an idempotent body to re-run.
- Raise a typed contention error on exhaustion, carrying SQLite's own wording.

## Outcome

The write path that failed in production now survives contention that outlasts the busy budget. Replay is safe by construction there: a contended transaction rolls back whole, and an exact replay of an already-recorded unit reports zero insertions, so re-running either lands the work or observes it already landed.

Only contention is replayed. An unrelated operational error surfaces on first sight rather than being retried three more times behind a misleading delay. Exhaustion still produces a classifiable transient outcome rather than an unclassified fault.

## Notes

The replay is applied only to the recording path, whose idempotence is a documented property. It was deliberately not applied to the transaction helper generally: a context manager cannot re-run its caller's body, and wrapping arbitrary write paths would replay operations whose idempotence has not been established.
