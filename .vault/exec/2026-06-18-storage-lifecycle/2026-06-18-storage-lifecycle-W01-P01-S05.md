---
tags:
  - '#exec'
  - '#storage-lifecycle'
date: '2026-06-25'
modified: '2026-06-25'
step_id: 'S05'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# Add an explicit watcher delete-carry-forward assertion covering the pending-set batching path

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`

## Description

Verified the explicit watcher delete-carry-forward assertion covering the cooldown-
suppressed pending-set batching path. Confirmed `test_watcher_evicts_cooldown_suppressed_delete`
primes the per-source cooldown with an unrelated edit, deletes a second file inside the
cooldown window, then leaves the tree quiet and asserts the idle tick flushes the
carried-forward deletion once the cooldown elapses - with no further filesystem event. A
sibling test asserts the idle tick does not bypass the cooldown (a deletion inside a long
window stays pending until the window elapses).

## Outcome

The step is genuinely shipped. The pending-set carry-forward and its anti-thrash bound are
both asserted by real-backend watcher tests, so the batching path that closes issue 192 on
a quiet tree is regression-protected. No new test was needed.

## Notes

No code changes; verify-and-tick of work delivered through pull request 197. The plan row
named a stress-and-watcher integration file; the carry-forward assertions live there as
`test_watcher_evicts_cooldown_suppressed_delete` and
`test_watcher_idle_tick_does_not_bypass_cooldown`.
