---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W03.P08` summary

Automatic watcher convergence now runs entirely through canonical manager jobs,
and watcher shutdown disables intake without cancelling that managed work or
closing storage beneath it.

- Modified: `src/vaultspec_rag/watcher.py`
- Modified: `src/vaultspec_rag/server/_watcher.py`
- Modified: `src/vaultspec_rag/server/__init__.py`
- Modified: `src/vaultspec_rag/service.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s19-watcher-stop-audit.md`

## Description

S18 moved vault and code watcher convergence onto the process-wide `JobManager`.
Dirty paths transfer atomically into immutable attempt generations, later
dirtiness coalesces behind paused work, resume keeps the same logical ID, and
cancelled or failed attempts retain dirty intent for bounded-backoff replacement
under a new canonical ID. Managed attempts use the production registry lease,
indexers, progress reporter, cooperative control token, and resource reporting.

S19 completed the ownership boundary. Watcher enablement is removed from public
state immediately on stop, while private state retains the intake coroutine and
joins exact watcher-origin manager attempts without cancellation or desired-state
mutation. Timeouts preserve retryable ownership, and start or reconfigure intent
is serialized until cleanup completes. The exact registry instance follows the
watcher into managed attempts, and explicit project closure atomically refuses a
live lease rather than invalidating its store.

Across the phase, real GPU/model/indexer/store probes covered lease ownership,
pause release, same-ID resumed convergence, cancellation, retained dirtiness,
replacement backoff, busy project closure, and successful eventual convergence.
Focused watcher, jobs, server, registry, CLI, filter, and ADR suites passed, as
did Ruff, type checking, scoped complexity, formatting, and diff validation.
Independent review approved both steps; S19 closed at Critical 0, High 0, Medium
0, Low 0.
