---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S12'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Make supervised start attach-or-spawn using the gate

## Scope

- `src/vaultspec_rag/qdrant_runtime/_supervise.py`

## Description

- Rewrote `start_supervised_from_config` to probe the port + read the identity + call
  `decide_qdrant_action` BEFORE resolving the binary, then act: attach (no spawn), refuse, or
  spawn. Binary resolution + hash verification now run only on the spawn path.
- Added attach mode to `QdrantSupervisor`: an `_attached` flag, `mark_attached()`, and an
  `is_alive()` that probes readiness in attached mode (no owned child); `stop()` already
  no-ops without a child so an attached server is never terminated.

## Outcome

A healthy, owned, capable managed Qdrant is now reused instead of re-spawned onto its
single-writer storage - the core P1 behavior. `ruff` and `ty` pass; verified end-to-end by
the S14 attach integration test (attaches, no child pid, alive).

## Notes

The attached supervisor is constructed with a sentinel binary path that is never executed in
attached mode. No blockers.
