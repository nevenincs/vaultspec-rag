---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S09'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add status-state fixtures asserting warming rendering, the distinct exit code, and absent-phase back-compat alongside the existing stopped and unreachable cases

## Scope

- `src/vaultspec_rag/tests/test_cli.py`

## Description

- Add TestWarmingStatusState to `src/vaultspec_rag/tests/test_cli.py`: phase reader tolerance, warming beats port/heartbeat crash signals, dead pid beats warming, explicit-port warming requires a live pid, absent-phase renders exactly as before, warming next-action says retry, and the daemon stamp merges/skips correctly against a real temp status dir.

## Outcome

Committed as 2ed542d (with S08). 9 passed.

## Notes

Live-pid-and-ours CLI-level rendering cannot be exercised without mocks (the identity check compares the service executable), so coverage is at the pure state-computer level per the no-mock mandate.
