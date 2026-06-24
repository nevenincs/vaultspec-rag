---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S18'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Reclaim a stale machine lock held by a dead owner on start

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Built crash-safe stale reclaim into `acquire_machine_lock`: when the lock file exists but
  its recorded holder pid is dead (via `_is_pid_alive`) - or is this process's own prior lock
  - the stale file is unlinked and acquisition retried, so a lock left by a crashed daemon
  never blocks the next start.

## Outcome

A stale lock from a dead holder is reclaimed and acquisition succeeds; a lock held by a live
foreign process is respected (refused). `ruff` and `ty` pass; verified by S19.

## Notes

Reclaim is the same orphan class the whole hardening addresses, applied to the service lock
itself, so the guard cannot become its own deadlock. No blockers.
