---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d60d16b0cef03a491bf1970d8156d0c125fb0f1fa8a3af53abacba04547beac6'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `S22 lifecycle integration`

## Scope

Audit `W03.P11.S22` coverage for real daemon restart and shutdown behavior in
`test_service_lifecycle.py`. The review covers durable queued and paused intent,
cooperative interruption after exact runtime-owner release, store-before-Qdrant
teardown ordering, restart reopening, process isolation, and compliance with the
project's real-behavior test policy.

## Findings

Independent review passed with no critical or high findings. Its two medium
corrections are applied: the lifecycle cases now rely on `_service_env` and its
established `_resolve_host_provisioned_qdrant` path instead of duplicating a
hardcoded home-directory lookup, and the changed-function complexity evidence
below reports the measured grades accurately.

## Recommendations

Close the plan row after the corrected focused verification remains green.
Preserve the test-owned status, storage, port, model, and process-group isolation
in any later revision.

## Verification evidence

- The two focused lifecycle cases pass together against real service processes,
  cached GPU models, the pinned manifest-backed Qdrant binary, production
  persistence decoding, production indexers, and real HTTP routes.
- The restart case crosses two daemon lives and observes the canonical manager
  restoring two active resources, dispatching only queued running intent, then
  restoring only the dormant paused resource on the second life.
- The shutdown case observes task, worker, limiter capacity, project lease,
  writer lock, and code pipeline ownership before signalling. It then observes
  terminal interruption only after all owners clear and the finished resource
  snapshot is durable.
- The shutdown log orders attempt completion before `ProjectSlot` closure,
  registry closure before the supervised Qdrant child stops, and clean service
  completion last. A second daemon opens the same isolated storage and serves a
  real code search.
- Ruff formatting and lint, BasedPyright, cognitive complexity, nesting depth,
  diff hygiene, and the prohibited-double scan pass. Changed functions have a
  maximum Xenon grade C and average grade B; the whole target file's existing
  baseline average remains grade B.
- Post-run process inspection finds no test-owned Python or Qdrant process, and
  the signalable fixture runs from its isolated temporary directory so Qdrant
  cannot publish a sentinel into the worktree.
