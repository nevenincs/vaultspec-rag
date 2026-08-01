---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:0a2382e983993ff5273947d38ae61c618dd45aa5c3365dd304b1597e6c4b82af'
step_id: 'S33'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Exercise a real large-corpus pause, resume, and cancel lifecycle proving convergence, attempt lineage, resource release, and no post-cancellation writes using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`

## Description

- Build a 384-document real vault corpus and start production managed indexing.
- Pause after a durable storage slice and join the exact attempt.
- Assert worker, task, lease, writer, pipeline, and limiter release.
- Resume through reconciliation attempt 2 and verify converged storage.
- Cancel a second large attempt at the real writer boundary and compare durable
  state before and after acknowledgement.

## Outcome

The real graphics processing unit (GPU) lifecycle passed in one focused run.
Pause acknowledged only after resource release, resume converged the complete
corpus with correct attempt lineage, and cancellation prevented all later point
and metadata writes. Ruff and BasedPyright pass. Independent review passed with
no critical, high, or medium findings.

## Notes

The selector ran once and completed in 193.58 seconds. It used the production
model, registry, manager, limiter, vault indexer, local Qdrant store, and writer
lock with no test doubles. One unused import was removed through static
verification without rerunning the expensive scenario.
