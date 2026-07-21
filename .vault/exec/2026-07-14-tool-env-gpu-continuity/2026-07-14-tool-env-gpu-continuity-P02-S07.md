---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S07'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Stamp phase warming into the status sidecar after machine-lock acquisition and before component warmup, and phase running at the lifespan yield, written by the daemon process only

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Add `_stamp_service_phase` to `src/vaultspec_rag/server/_lifespan.py`: best-effort merge into service.json via `serviceclient._discovery._status_file`, skip-if-absent, never raises, debug-logged failures per the no-swallow rule.
- Stamp warming immediately after `_claim_machine_singleton()` and running right after `_start_components()` returns (immediately before the lifespan yield).

## Outcome

Committed as 2b7390f. Direct file-merge test in TestWarmingStatusState; the lifecycle-inertness ADR regression suite stays green (no cli import added to the server domain).

## Notes

If the daemon wedges during warmup the status remains warming indefinitely (no staleness timeout on the phase); the pid-alive guard still degrades to crashed once the process dies.
