---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S40'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Extract JobManager ownership and lifecycle orchestration, leave jobs.py as the legacy compatibility and dispatch facade, and verify unchanged public behavior using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/job_manager.py`
- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/tests/test_jobs_unit.py`
- `src/vaultspec_rag/tests/integration/test_jobs_registry.py`

## Description

- Create `job_manager` as the one-way service-domain owner of canonical job
  lifecycle, live task/control handles, dirty persistence, retention, and recovery.
- Reduce `jobs` to the legacy registry/background-dispatch compatibility facade
  while re-exporting the exact canonical manager and model objects.
- Share one `MAX_RECORDS` definition across manager retention, the legacy ring,
  and server compatibility imports.
- Preserve the established `vaultspec_rag.jobs` logger surface and every extracted
  lifecycle, persistence, path, control-signal, and runtime behavior.
- Add direct identity and fresh-interpreter import-boundary regressions against
  production modules.
- Verify the extraction with Ruff, ty, strict BasedPyright, job-control/jobs unit
  tests, real persistence integration, broader non-GPU registry integration, and
  independent review.

## Outcome

Completed. `JobManager` and its private ownership types now live in
`job_manager`, which depends on models, persistence, configuration, and
control typing without importing `jobs`. The legacy module imports and
re-exports the exact manager object, retains all existing dispatch behavior,
and consumes the same bounded-history constant.

## Notes

Independent review found one High issue in the new subprocess regression: a
shared editable environment could resolve another worktree. The probe now
explicitly prepends its own `src` root, and re-review passed with no remaining
Critical or High findings.

An early relative patch-path error briefly rewrote the shared main worktree.
Execution stopped immediately; the coordinator restored the original files and
independently hash-verified the recovery before isolated work resumed. No data
loss remained. All subsequent patches used absolute isolated-worktree targets
with before/after status checks.

The required non-GPU gates passed: 77 focused unit/persistence tests and all 20
non-GPU jobs registry tests. The two GPU subprocess registry cases and final
RAG/GPU index refresh were not run because this phase changes only module
ownership and the environment has the already-recorded GPU out-of-memory
condition.
