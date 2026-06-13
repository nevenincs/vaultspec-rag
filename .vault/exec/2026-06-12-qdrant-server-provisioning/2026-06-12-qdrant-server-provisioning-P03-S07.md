---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-12'
step_id: 'S07'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Add qdrant liveness with one bounded auto-restart to the heartbeat, record the child PID in the service status file, and surface a qdrant block in the service-state read

## Scope

- `src/vaultspec_rag/server/_lifecycle.py`
- `src/vaultspec_rag/api.py`

## Description

- Merge `qdrant_pid` / `qdrant_alive` / `qdrant_port` into `service.json` on every
  heartbeat tick when a child is supervised (the lifespan's immediate first tick lands
  the PID right after spawn).
- Add `_qdrant_liveness_tick()` riding the existing heartbeat loop (no new background
  thread): one bounded auto-restart per daemon lifetime, then a structured
  `qdrant_dead` warning while degraded state surfaces through health/state reads.
- Add the `qdrant` block to `api.get_service_state` via `qdrant_runtime.runtime_state()`
  so the route, MCP tool, and CLI in-process fallback all report the same
  service-domain state.

## Outcome

Heartbeat and state surfaces share one service-domain read; unit suite, ty strict,
and complexity gates green.

## Notes

None.
