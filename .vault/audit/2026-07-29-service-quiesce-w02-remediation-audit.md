---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
related: []
---

# `service-quiesce` audit: `w02 remediation`

## Scope

Read-only review of W02's controller, registry transition coordinator, search admission route, and CPU-only regression coverage against the accepted `service-quiesce` ADR and its W02 plan. The review examined admission coalescing, lock order, error handling, the exact quiescing-search response, and recovery-test quality. No service, RAG endpoint, CUDA allocation, or GPU test was run.

## Findings

### resume-persistence-strands-jobs | high | A reported successful resume can leave same-ID quiesced jobs permanently inactive

`ServiceRegistry._resume_resources_once` calls `complete_warming`, which opens a new admission epoch and produces the successful `running` transition, before it calls `resume_quiesced_attempts`; it ignores that method's result. When that manager method encounters a persistence error, it returns an empty tuple. For an unpublished error it restores each job to `paused` with desired state `running`; for a published-but-not-durable error it retains the queued snapshot but still returns before `_schedule_dispatch`. In either case no runtime is scheduled, yet the registry returns the successful running transition. A later `resume_resources` call takes the already-running shortcut and does not retry reconciliation, so the same logical jobs can remain stranded until unrelated recovery. This violates the W02 requirement that globally quiesced jobs converge under their original logical IDs and that completed resume truthfully includes that convergence. The new transition tests exercise successful convergence and transition wait behavior but not either persistence-error branch.

## Recommendations

- For `resume-persistence-strands-jobs`, make lifecycle success contingent on completed durable job reconciliation, or retain an explicit retryable reconciliation state that idempotent resume invokes until every desired-running quiesced job has been scheduled. Add CPU-only real durable-write failure coverage for both unpublished and published persistence outcomes, asserting no successful `running` result strands a same-ID job without a runtime or scheduled dispatch.
