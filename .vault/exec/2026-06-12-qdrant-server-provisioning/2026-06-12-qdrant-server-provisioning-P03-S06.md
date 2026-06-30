---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S06'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Spawn qdrant before model load in the service lifespan, publish the in-process server URL, stop qdrant last among data components, and add a qdrant block to health

## Scope

- `src/vaultspec_rag/server/_lifespan.py`
- `src/vaultspec_rag/server/_state.py`

## Description

- Add `start_supervised_from_config()` to the runtime package: resolve the binary
  (env > provisioned > PATH), re-hash a provisioned binary against its manifest digest
  before execution, build the supervisor from the config knobs (port, storage dir,
  `qdrant.log` beside the service log), start it, and install it as the process-wide
  active supervisor.
- Spawn the qdrant child in `service_lifespan` BEFORE model load so a broken binary
  fails startup with no GPU memory committed; publish the in-process URL via the
  qdrant URL env var so registry stores open server-mode from the first lease. An
  operator-set URL wins over spawning (remote escape hatch).
- Shutdown ordering in the lifespan finally: watchers, then stores, then the qdrant
  child last among data components.
- Add a `qdrant` block to the health payload via the shared `runtime_state()` read and
  degrade overall status when a supervised child is dead.

## Outcome

Full unit suite for server modules green (143 tests across test_server + qdrant
runtime); ty strict and complexity gates pass.

## Notes

None.
