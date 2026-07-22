---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S29'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Interrupt and restart a real multi-segment index and prove replay is limited to the last unrecorded unit

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Interrupt a real multi-unit code stream after production storage publishes durable work.
- Verify the consumer and worker pool unwind before the writer boundary is released.
- Resume against the same vector store and compatible generation.
- Combine real-store convergence with SQLite segment evidence proving committed units are skipped and only unconfirmed units remain eligible.

## Outcome

Interrupted code indexing preserves exact storage-confirmed progress, releases execution resources, and resumes to the current source state without restarting committed segment work. A storage/checkpoint crash gap remains bounded to replay of the single unrecorded idempotent unit.

## Notes

Acceptance uses the production weighted code pipeline, real vector storage, a production control token, and the transactional SQLite ledger. No fakes, mocks, patches, skips, or expected failures are used.
