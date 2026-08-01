---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a3d00bd386727647d2111ba2fd9173321976b0065702634e18a21f480777ab4e'
step_id: 'S22'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify real-daemon recovery from deleted, stale, and foreign pointers without PID change or process termination

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

- Corrupt a live isolated daemon's pointer three ways in turn - deleted, stale, and naming
  a foreign process - and reconcile after each.
- Assert convergence, that the republished pointer names the same live daemon and port,
  and that the daemon is neither killed nor restarted across any round.
- Assert a further reconcile against the converged machine reports already-converged.

## Outcome

Recovery from every corrupted pointer shape is proven to happen through the owner's own
heartbeat, with the daemon's process identity unchanged throughout, and the verb is proven
idempotent.

## Notes

The unchanged-identity assertion is the load-bearing one. A reconcile that silently
restarted the daemon would repair discovery just as visibly while destroying in-flight
work, so the test pins the serving process identity through the health endpoint after every
round rather than only checking that the records look right.
