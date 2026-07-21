---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S39'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Extract the versioned state codec and atomic filesystem store into a focused persistence module using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/job_persistence.py`
- `src/vaultspec_rag/jobs.py`

## Description

- Create `src/vaultspec_rag/job_persistence.py` with the v1 JSON codec,
  generation validation, idempotency encoding, and atomic state-file store.
- Modify `src/vaultspec_rag/jobs.py` to delegate durable load and save
  operations while retaining lifecycle, capacity, retention, dirty-state,
  rollback, and outcome ownership.
- Modify `src/vaultspec_rag/tests/integration/test_jobs_registry.py` with real
  filesystem coverage for strict validation, legacy v1 restoration, concurrent
  atomic reads, rollback, flush, and restart behavior.
- Delegate durable load and save operations from `JobManager` while retaining
  the service-domain persistence policy.
- Make replacement durable through POSIX parent-directory fsync and Windows
  write-through replacement with bounded sharing retries.
- Distinguish definitely-unpublished failures from published or uncertain
  generations so rollback and live control signals follow disk visibility.
- Preserve the committed v1 start-paused representation through narrow decode
  normalization and canonical migration.

## Outcome

Completed. `jobs` now depends one-way on a focused, dependency-light persistence
module, and importing that module does not import `jobs`. The on-disk schema and
valid v1 serialization remain compatible while durability and validation are
stricter.

## Notes

The initial formal review identified directory-entry durability and timestamp
validation gaps. A follow-up review identified the legacy v1 start-paused shape;
all High findings were resolved, and the final independent verdict was PASS.
Post-publication fsync failure was reviewed statically because it cannot be safely
forced on the Windows host without prohibited test doubles. Ruff, ty, strict
BasedPyright, and 75 focused unit/integration tests passed. S40 was not started.
The final vault and code RAG refresh was accepted by the shared service, but both
requested jobs ended with the service's existing CUDA out-of-memory condition;
the occupied GPU was not retried.
