---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W03.P11` summary

Watcher and service-lifecycle integration now prove that manager-owned work
preserves convergence intent while pause, cancellation, restart, explicit
watcher stop, and daemon shutdown release resources truthfully.

- Modified: `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`
- Modified: `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s21-orchestration-audit.md`
- Created: `.vault/audit/2026-07-22-service-job-control-s22-lifecycle-integration-audit.md`
- Created: `.vault/exec/2026-07-21-service-job-control/2026-07-21-service-job-control-W03-P11-S21.md`
- Created: `.vault/exec/2026-07-21-service-job-control/2026-07-21-service-job-control-W03-P11-S22.md`

## Description

S21 verifies watcher convergence through the production manager, registry,
indexers, local storage, and filesystem intake. Paused work releases every
execution owner while retaining one convergence slot. Later dirtiness
coalesces into the same logical job, and resume converges both generations.
Cancellation retains dirty intent, keeps watcher intake enabled, and schedules
a distinct replacement after bounded backoff. Explicit watcher stop disables
new intake and waits for manager-owned cleanup without cancelling the job.

S22 verifies service restart and shutdown through real subprocess daemons,
production persistence decoding, cached GPU models, pinned Qdrant
verification, real indexers, and HTTP routes. Restart dispatches durable queued
running intent and preserves paused intent across service lives. Graceful
shutdown records active work as interrupted only after task, worker, limiter,
lease, writer-lock, and pipeline release. Stores close after attempt completion
and before supervised Qdrant termination. A second daemon reopens the isolated
storage and serves code search.

Both steps preserve test-owned status, storage, ports, process groups, and
manager state. Focused behavior suites, Ruff, formatting, strict typing,
complexity, syntax, diff hygiene, and prohibited-double checks pass.
Independent review approved S21 with no findings. S22 review returned PASS with
no critical or high findings after its two medium corrections were applied.
