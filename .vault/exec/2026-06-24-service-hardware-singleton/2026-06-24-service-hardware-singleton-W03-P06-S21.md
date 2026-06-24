---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S21'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Integration-test that a dead orphan is reaped and a live holder is never killed

## Scope

- `src/vaultspec_rag/tests/integration/test_qdrant_orphan_reap.py`

## Description

- Authored `test_qdrant_orphan_reap.py` (no mocks, no GPU): reaps a real spawned subprocess
  and asserts it is gone; asserts a non-positive pid is not reaped and an already-dead pid is
  a no-op success; and asserts the decision layer routes a live, owned, capable server to
  `attach` (never `reap`) while a dead-owner-holding-the-port routes to `reap_then_spawn`.

## Outcome

Reaping is verified against a real process, and the "a live holder is never reaped" guarantee
is pinned at the decision boundary. `ruff` and `ty` pass; 5 tests in the module pass.

## Notes

The live-holder safety is enforced by `decide_qdrant_action` (only a dead-owner orphan routes
to reap), so the reaper is never invoked on a process whose owning service is alive. No
blockers.
