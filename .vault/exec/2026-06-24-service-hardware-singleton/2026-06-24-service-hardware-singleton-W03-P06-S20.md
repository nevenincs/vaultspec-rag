---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S20'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Reap a provably-dead managed qdrant orphan before spawning

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Added a backward-compatible `qdrant_pid` field (default 0) to `QdrantIdentity`, the writer,
  and the reader, and recorded `supervisor.pid` in the sidecar on spawn - so a later start can
  reap the actual Qdrant child, not the (dead) owning service.
- Added `reap_qdrant_orphan(pid)` to `_resolve.py`: graceful terminate escalating to a hard
  kill (Windows `taskkill /F /T`; POSIX SIGTERM then SIGKILL), then verifies the pid is gone.
- Rewired the `reap_then_spawn` branch of `start_supervised_from_config` to reap the recorded
  child pid and fall through to spawn on success (refuse with guidance if the pid is unknown
  or the reap fails).

## Outcome

The exact live incident now auto-recovers: a managed Qdrant orphan holding the port is reaped
and a fresh child spawned, instead of an opaque 300s hang. `ruff` and `ty` pass; verified by
S21 (reaps a real spawned process) and the full 26-test qdrant suite (no regression from the
`qdrant_pid` addition).

## Notes

`qdrant_pid` defaults to 0 so pre-existing identity records (and the tests that omit it) keep
working; a 0/unknown child pid routes to a clear refusal rather than a blind kill. No blockers.
