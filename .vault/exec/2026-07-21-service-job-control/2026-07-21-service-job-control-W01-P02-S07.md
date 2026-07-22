---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Implement atomic durable-before-dispatch persistence and queued, paused, and interrupted restart recovery using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add an injectable manager state path so real tests and managed service storage remain isolated.
- Serialize canonical active resources and active idempotency bindings through one versioned schema.
- Flush and atomically replace the state file before admitting, dispatching, or applying lifecycle changes.
- Roll back in-memory mutations when durable state cannot be committed.
- Restore queued and paused resources under the same IDs and convert prior live attempts to immutable interrupted history.
- Reject corrupt, incompatible, duplicate, or over-capacity persisted state without partial application.

## Outcome

Managed jobs now have one crash-safe persistence boundary. Accepted queued work is durable
before it can run, paused intent survives restart, and unacknowledged live work returns as
truthful interrupted history instead of disappearing or being mislabeled cancelled.

## Notes

Ruff, formatting, `ty`, strict BasedPyright, and all 49 focused unit tests passed. Real
temporary-directory probes verified atomic replacement, queued/paused/live recovery,
idempotency replay, corrupt-file isolation, absence of orphan temp files, and rollback when
the persistence parent cannot be created.
