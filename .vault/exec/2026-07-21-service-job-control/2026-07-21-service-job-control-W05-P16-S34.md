---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S34'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Exercise a real restart lifecycle proving durable queued dispatch, persistent pause, interrupted attempts, linked retry, and terminal-history deletion using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`

## Description

- Persist queued, paused, and running job resources through the canonical manager.
- Capture a real production indexing attempt at the writer boundary.
- Restore through the production service startup, rebinding, and dispatch path.
- Execute queued work and a linked retry against the real registry and local store.
- Prove persistent pause and durable terminal-history deletion after restart.
- Drain both pre-restart and current manager generations before store closure.

## Outcome

The restart lifecycle passes. Production startup restored the exact queued and
paused identities, dispatched only runnable work, converted the real abandoned
attempt to `interrupted`, completed a linked retry, and persisted deletion of
the interrupted parent. All manager, lease, writer, limiter, and store owners
were released. Ruff and BasedPyright pass, the focused scenario passes, and
independent review reports no findings.

## Notes

Review replaced an initial manual restart path with the production lifecycle
entry point and strengthened teardown to drain both singleton generations. The
final focused run completed in 29.27 seconds with a real GPU model and local
Qdrant store. No test doubles or monkeypatching were used.
