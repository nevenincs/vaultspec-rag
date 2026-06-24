---
tags:
  - '#exec'
  - '#service-doctor-liveness'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S07'
related:
  - "[[2026-06-24-service-doctor-liveness-plan]]"
---

# Make daemon survival independent of the launching shell: on a breakaway denial, detach so the daemon outlives the parent or fail loudly instead of the silent doomed fallback

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Remediated daemon survival: on a breakaway denial, attempt a console-detached spawn (DETACHED_PROCESS + new process group) so the daemon outlives the parent, and fail loudly with a new `DaemonBreakawayError` if detachment is also refused - no more silent shell-bound daemon. Machine-lock and lifespan surfaces left untouched (owned by the singleton campaign).

## Outcome

A daemon started from a terminal no longer dies silently when the terminal closes.

## Notes

Implemented via a high-reasoning executor; ruff/ty/pytest re-verified by the orchestrator (277 passed across process/singleton/lifecycle/CLI; 11 in the doctor/flapping suites). Singleton surfaces (\_machine_lock, \_lifespan) left untouched.
