---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Implement exact-ID active and runtime ownership, bounded terminal history, admission, active-work deduplication, and idempotency keys using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Add one thread-safe `JobManager` with independent active and terminal ownership.
- Keep nonterminal jobs exact-addressable and refuse admission at the configured bound.
- Replay idempotent creates, reject key reuse with changed input, and deduplicate equivalent active work before capacity checks.
- Retain task and cooperative-control references by exact job ID and release them only when the owning task identity matches.
- Bound terminal history independently and expire its associated idempotency bindings on eviction.

## Outcome

The service domain now owns canonical job resources through an admission-safe manager.
Controllable work cannot be evicted by history growth, repeated submissions resolve to
the same logical resource, and stale attempt cleanup cannot detach a newer runtime.

## Notes

Ruff and `ty` passed, as did a real concurrent submission probe covering exact-ID
lookup and active-work deduplication. The existing focused suites passed 56 tests; two
live-service fixture setups were unavailable because this worktree has no provisioned
Qdrant server binary, before either job-registry test body ran.
