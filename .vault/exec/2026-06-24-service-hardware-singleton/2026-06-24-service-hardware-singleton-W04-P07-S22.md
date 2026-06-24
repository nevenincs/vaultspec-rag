---
tags:
  - '#exec'
  - '#service-hardware-singleton'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S22'
related:
  - "[[2026-06-24-service-hardware-singleton-plan]]"
---




# Adversarial: N concurrent starts yield exactly one service and one qdrant

## Scope

- `src/vaultspec_rag/tests/integration/test_adversarial_singleton.py`

## Description

- Authored `test_adversarial_singleton.py` with a REAL multi-process race: 8 separate
  processes (spawn) concurrently call `acquire_machine_lock` against one isolated lock path;
  the test asserts exactly one wins.
- Building this exposed and fixed a real race in the lock: a loser hitting `FileExistsError`
  during the winner's create-then-write window read an empty file (holder=0) and would
  reclaim it, yielding two winners. Hardened `acquire_machine_lock` to treat an empty/holder-0
  file as held (never reclaim), only reclaiming a nonzero-dead or own-pid holder.

## Outcome

8 concurrent starts converge to exactly one winner. The fix removed a genuine double-acquire
race that only a multi-process test surfaces. `ruff` and `ty` pass.

## Notes

The winner sleeps briefly so its pid stays alive across the race window (a winner that exited
immediately would look like a stale dead holder). The pre-existing `test_machine_singleton.py`
cases still pass under the hardened reclaim rule. No blockers.
