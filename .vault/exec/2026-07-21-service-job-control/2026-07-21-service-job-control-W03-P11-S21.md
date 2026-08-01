---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8911aa02447c3d91244ab150e1d6946ce8ed6ea52b4591cf9bf53dea6fc6b991'
step_id: 'S21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify real watcher pause coalescing, cancellation dirtiness, replacement expectations, explicit watcher stop, and cleanup joining using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

- Migrate watcher integration coverage from standalone stores to the canonical
  production registry, manager, and server watcher owner.
- Isolate managed status, local Qdrant storage, limiter state, watcher drains,
  project slots, and manager state for every watcher test.
- Verify paused watcher work releases its task, worker, capacity, lease, writer,
  and pipeline ownership while retaining one convergence job.
- Add later filesystem dirtiness while paused and prove resume uses the same job
  ID, creates a reconcile attempt, and indexes both generations.
- Stop watcher intake while the resumed attempt is blocked on the real writer
  lock and prove cleanup remains pending until the attempt naturally releases.
- Cancel a live watcher attempt, prove watcher intake stays enabled, and verify a
  delayed distinct-ID replacement converges retained and later dirtiness.
- Preserve and re-run the existing watcher detection and cooldown regression
  coverage through the manager-owned runtime.

## Outcome

The target integration file now exercises one production ownership path from
filesystem intake through `JobManager`, the registry lease, real indexers, local
Qdrant storage, and bounded watcher cleanup. The obsolete double-store topology
that failed after watcher execution moved into the manager was removed.

The two new lifecycle cases passed together, and the full target file passed all
seven tests. Ruff lint and formatting passed, BasedPyright reported zero errors
and warnings, scoped Xenon and cognitive-complexity gates passed, the
prohibited-test-double scan found no matches, and `git diff --check` passed.
Independent review approved the step with zero critical, high, medium, or low
findings.

## Notes

The initial five-test baseline produced three passes and two failures because
the old tests held a standalone local store while manager-owned watcher work
opened the canonical registry store for the same root. The corrected topology
uses one real registry slot and resolves that storage-lock conflict without
weakening any assertion.

The isolated worktree had no semantic code or vault index, so grounding used the
documented full-source and exact-symbol fallback. No production files changed,
no test was skipped or marked as an expected failure, and no data was lost.

`W03.P11` remains open because `S22` is not complete, so no Phase Summary is
created by this step.
