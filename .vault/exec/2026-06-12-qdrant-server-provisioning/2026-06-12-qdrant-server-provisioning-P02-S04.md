---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S04'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Implement qdrant child supervision: loopback spawn with env-injected storage and ports, readyz poll with backoff, graceful terminate, and Windows kill-on-close Job Object

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Add `qdrant_runtime/_supervise.py`: `QdrantSupervisor` owning one loopback qdrant child
  configured via `QDRANT__*` env vars (host 127.0.0.1, HTTP port, gRPC port defaulting to
  one below HTTP, storage and snapshots paths, telemetry disabled), `/readyz` polling with
  exponential backoff and a liveness guard, graceful terminate with bounded waits and
  force-kill fallback, a single-attempt `restart()` counter for the heartbeat, and a
  Windows kill-on-close Job Object (`CreateJobObjectW` + KILL_ON_JOB_CLOSE +
  `AssignProcessToJobObject` via ctypes) so a hard daemon death can never orphan the child.
- Expose `set_active_supervisor` / `active_supervisor` / `runtime_state()` as the
  service-domain qdrant state read shared by health, heartbeat, and service-state surfaces.

## Outcome

Module type-checks (ty strict) and lints clean; behaviour exercised end-to-end by the
P05 integration test against the real binary (spawn, ready, reap).

## Notes

None.
