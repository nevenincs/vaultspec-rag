---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Thread the retained lease through startup and quiesce heartbeat before owner cleanup and lock release

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Acquire one retained `MachineLockLease` before any subordinate component starts and pass
  its publisher through phase stamping, Qdrant identity publication, the heartbeat loop,
  and shutdown.
- Replace read-before-merge heartbeat and unauthenticated deletion paths with complete
  owner-authenticated snapshots and publisher-owned cleanup.
- Quiesce the synchronous publisher before cancelling periodic tasks so an already-running
  worker finishes behind the same guard and every later tick is inert.
- Delete both discovery views before releasing the singleton, and retain the lease for the
  registered exit retry when either deletion fails.
- Migrate focused production tests from mutable module patching to real isolated locks,
  paths, status locks, and owner publishers.

## Outcome

The daemon now carries one unforgeable lease from singleton acquisition through final
cleanup. Normal shutdown cannot release ownership while a heartbeat can still publish, and
it cannot admit a successor beneath stale discovery when owner cleanup fails.

## Notes

Ruff formatting and lint passed across all nine affected files, BasedPyright reported zero
diagnostics, and the focused real-behavior suite passed 23 tests. A broader server run also
passed 133 tests; its three failures belong to the concurrently open mandatory-preflight
contract remediation and are not used as S07 evidence. No operator daemon or managed
storage was touched.
