---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S17'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify paused attempts release limiter, lease, writer ownership, thread, and pipeline resources and cancelled attempts make no later writes using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_index_job_control.py`

## Description

- Exercise compatibility reindex entry points through the production singleton
  registry, cached CUDA embedding model, embedded local Qdrant, canonical
  `JobManager`, AnyIO limiter, real indexers, spawn workers, and consumer thread.
- Prove vault and code pause acknowledgements follow task, worker, capacity,
  lease, writer, pipeline, process, and consumer release.
- Resume vault and code work under the same logical ID with a fresh reconcile
  attempt and verify complete Qdrant payload and metadata convergence.
- Cancel a partially published vault attempt, freeze its canonical snapshot,
  points, payloads, and metadata after acknowledgement, and prove cancellation
  remains absorbing.
- Force a real incompatible-Qdrant-vector failure behind production GPU and
  point locks and prove the application error wins over pending cancellation.
- Fail fixture cleanup closed when any bounded join or active-resource check
  fails, preserving stores and limiter ownership reachable by a live worker.

## Outcome

The service facade now has real integration evidence for the complete
manager-owned indexing lifecycle. A clean code attempt was observed with its
spawn producer pool and sole GPU consumer live, requested to pause after real
publication, and reached canonical `paused` only after every reported and
physical resource was released. Its same exact ID then ran attempt 2 with
`resumed_from_attempt=1` and `resume_strategy=reconcile` and converged the real
collection and metadata. Vault pause/resume passed the same identity and
release checks.

A running vault cancellation acknowledged only after release; its job snapshot,
point IDs, count, payloads, and metadata remained byte-for-byte stable through
the post-acknowledgement window. Repeated cancellation was idempotent and resume
was rejected. A deliberately incompatible real Qdrant collection raised a
non-control application error while cancellation was pending; `failed` won and
all resources were released.

The seven pre-existing target tests passed, all four new managed-facade tests
passed in one production-model run, and ten worker/GPU/registry/facade boundary
regressions passed. Ruff, formatting, ty, BasedPyright, collection of all eleven
target cases, and `git diff --check` passed. Independent re-review approved at
Critical 0, High 0, Medium 0, Low 0.

## Notes

The first managed run exposed two test-synchronization mistakes rather than
product failures: incremental code indexing does not own the clean full-index
producer/consumer pipeline, and a point lock taken before dispatch blocks the
incremental delete phase before embedding. The tests were corrected to exercise
the clean pipeline and to stage GPU-lock then point-lock ownership around the
real upsert. Review then found and drove remediation of missing canonical code
pause coverage, unsafe test teardown after join timeout, and a narrow 20-second
real-work deadline. Final teardown refuses to close or reset reachable resources,
and managed stages use 60-second bounds under the 300-second test timeout.

No fake, mock, stub, patch, monkeypatch, skip, or expected failure was used. The
registry model was loaded only through its public production API. The previously
recorded semantic RAG refresh CUDA out-of-memory path was not retried.
