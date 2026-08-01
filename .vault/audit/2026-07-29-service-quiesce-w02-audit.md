---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:5f188ce2371a53b352bd324a7c0a96e0b3c58e75ec4e992d917ad4a92f30de96'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` audit: `W02 resource-quiesce implementation review`

## Scope

Read-only W02 audit of the accepted resource-quiesce controller, registry lifecycle, managed job and search admission, streaming checkpoints, and watcher intake/defer path against the accepted `service-quiesce` ADR and plan. No service, RAG, or GPU execution was performed.

## Findings

### watcher-admission-race | high | Quiesce can turn watcher work into a retry failure instead of deferred work

`_reconcile_watcher_slot` observes `running` before it creates and dispatches a watcher job. If pause closes admission after that observation but before `start_attempt`, `start_attempt` returns `quiesce_admission_closed`; `_dispatch_created_watcher_job` then calls `_finish_unstarted_watcher_failure`, which invokes `fail_unstarted`, mutates retry state through `_settle_retry_failure`, and schedules a replacement. This contradicts the required closed-admission behavior of retaining dirty paths and retry generation unchanged for deferred convergence. The `QuiesceRequested` conversion in `_run_managed_index_attempt` cannot cover this path because the worker never started. The existing watcher tests cover only a controller already closed before reconciliation, not this interleaving.

Resolution rechecked 2026-07-30: `defer_unstarted_for_quiesce` now changes only a queued, runtime-free job to `paused` with desired state `running` and persists that state. `dispatch_async` suppresses the cancelled pre-start task's completion callback when ownership was never established, and `_dispatch_created_watcher_job` selects that defer path for `quiesce_admission_closed` rather than retry settlement. The real manager/controller/retry-policy regression test proves dirty paths and the admitted durable retry state remain unchanged with no held resources. `resume_quiesced_attempts` admits this job class only after the controller snapshot is `running`; service resume invokes it only after successful warming completes. Static recheck found no remaining issue in this path; tests were not run.

## Recommendations

- For `watcher-admission-race`, make closed admission during queued-to-start dispatch a quiesce/defer outcome: preserve dirty paths and durable retry state, and leave the same logical watcher work eligible only after the controller returns to `running`. Add a real interleaving test that closes admission between watcher observation and `start_attempt` and proves the retry generation does not advance.
