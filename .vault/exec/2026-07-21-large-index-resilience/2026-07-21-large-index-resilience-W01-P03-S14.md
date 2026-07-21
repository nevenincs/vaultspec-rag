---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S14'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Implement durable-progress deadlines and interruptible queue, retry, and shutdown polling

## Scope

- `src/vaultspec_rag/indexer/_run_policy.py`
- `src/vaultspec_rag/tests/test_run_policy.py`

## Description

- Establish one thread-safe monotonic clock for time since durable progress.
- Latch typed no-progress expiry across producer, consumer, retry, and control checkpoints.
- Add interruptible waits and bounded queue operations without losing ownership after successful transfer.
- Add independent hard-cap cleanup operations for sentinel delivery and worker joining after run unwind.
- Expose the store's limited remaining-budget and interruptible-wait capabilities without granting clock-reset authority.

## Outcome

Index attempts now have one reusable liveness authority for queue waits, retry
waits, cooperative control, and bounded cleanup. Only ledger-unit and
finalization-phase commit events may advance the clock. Expiry returns the
shared `no_progress_timeout` outcome, while cleanup retains an independent
bounded opportunity to deliver a sentinel and join a worker.

Forty-six focused run-policy, store-write, and job-control tests passed using
real clocks, threads, queues, and control tokens. Ruff and strict type checks
passed. Independent review found no remaining critical or high issue.

## Notes

Active indexer wiring is deliberately deferred until storage-confirmed ledger
commits exist. Queue motion, encoding, logging, and uncheckpointed Qdrant
success are not durable progress and therefore cannot safely reset the clock.
