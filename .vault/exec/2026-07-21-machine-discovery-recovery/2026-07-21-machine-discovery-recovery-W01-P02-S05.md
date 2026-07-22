---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify a real foreign lock holder blocks pointer publication and deletion while the retained owner succeeds

## Scope

- `src/vaultspec_rag/tests/integration/test_machine_singleton.py`
- `src/vaultspec_rag/_machine_lock.py`

## Description

- Publish a sentinel pointer under a real retained owner lease, release it, and start a distinct foreign lock-owning subprocess.
- Prove acquisition reports the foreign holder and a stale former-owner lease cannot replace or delete the sentinel.
- Stop the exact test-owned holder only after observing real OS-lock release.
- Reacquire a new retained lease and prove wrong-PID publication fails without mutation.
- Prove the current owner atomically replaces and deletes the pointer without leaving a temporary file.

## Outcome

The real Windows advisory-lock boundary now has end-to-end adversarial coverage. Foreign
ownership leaves discovery unchanged, stale capability reuse fails even when the descriptor
number could be recycled, and only the newly retained owner can publish or delete.

## Notes

The publication input was widened from mutable `dict` to read-only `Mapping` after strict
type checking exposed dictionary invariance in the production-behavior test. Ruff lint and
formatting passed, BasedPyright reported zero diagnostics, and all six machine-singleton
integration tests passed with real subprocess and OS-lock behavior.
