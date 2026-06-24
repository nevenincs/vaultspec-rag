---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S19'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---

# Integration-test that a second start refuses and a stale lock is reclaimed

## Scope

- `src/vaultspec_rag/tests/integration/test_machine_singleton.py`

## Description

- Authored `test_machine_singleton.py` (no mocks, no GPU): an env-isolated lock; asserts
  acquire/release; spawns a real subprocess as a live foreign holder and asserts a second
  acquire is refused with that holder's pid; and asserts a dead-holder stale lock is reclaimed.

## Outcome

3 tests pass. The machine-singleton primitive (acquire, refuse-on-live-holder, reclaim-stale)
is verified against the real filesystem and a real process. `ruff` and `ty` pass.

## Notes

The foreign-holder case uses a genuinely-running child process (not a fabricated pid), so the
"live holder refuses a second service" guarantee is exercised for real. No blockers.
