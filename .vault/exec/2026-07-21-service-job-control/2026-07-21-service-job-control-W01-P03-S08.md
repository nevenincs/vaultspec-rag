---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S08'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify the transition matrix, idempotency, stale revisions, admission, deduplication, retry, deletion, and terminal immutability using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/test_jobs_unit.py`

## Description

- Drive concurrent equivalent submissions through the production manager and verify one exact resource owns them.
- Verify admission refusal, full-ID lookup, idempotency replay, and conflicting key reuse.
- Exercise stale revision handling, immediate queued pause, resume attempt lineage, and delivered pause/resume races.
- Exercise immediate and cooperative cancellation, pause/cancel precedence, and terminal transition rejection.
- Verify first-terminal-writer-wins, linked retry, force refusal, and terminal-only deletion.

## Outcome

The manager's public lifecycle contract is covered by real threads and asyncio tasks. The
tests prove that contention does not duplicate logical work, stale callbacks do not rewrite
new attempts, cancellation remains absorbing, and terminal history stays immutable.

## Notes

All five new managed-job tests passed. Ruff, formatting, `ty`, and strict BasedPyright also
passed for the expanded unit module; no fakes, mocks, patches, skips, or mirrored business
logic were introduced.
