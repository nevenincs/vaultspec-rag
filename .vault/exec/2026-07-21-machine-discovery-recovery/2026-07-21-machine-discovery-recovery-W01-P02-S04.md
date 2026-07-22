---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S04'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Define a retained machine-lock lease and owner-checked atomic pointer publish and delete primitives

## Scope

- `src/vaultspec_rag/_machine_lock.py`

## Description

- Retain an identity-checked `MachineLockLease` around the descriptor that owns the real OS advisory lock.
- Reject publication and deletion unless the caller presents the exact active process-local lease.
- Require every published pointer payload to name the lease-owning PID.
- Serialize before mutation and atomically replace through a unique same-directory temporary file.
- Serialize pointer mutation with lease release so ownership cannot disappear between authorization and the filesystem effect.

## Outcome

Machine-pointer mutation now has an explicit process-local authority boundary. A copied,
reconstructed, released, foreign-process, or wrong-PID capability cannot publish or delete
discovery, while the retained owner can perform atomic replacement and idempotent cleanup.

## Notes

Ruff lint and formatting passed, BasedPyright reported zero diagnostics, and the existing
five-test real OS-lock suite passed on Windows. The next Step adds direct foreign-holder,
stale-lease, payload-identity, atomic-publication, and owner-deletion regression coverage.
