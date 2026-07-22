---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S12'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify ready, absent, missing, invalid, stale, foreign-PID, and legacy fallback resolution against real locks

## Scope

- `src/vaultspec_rag/tests/test_machine_discovery_resolution.py`

## Description

- Cover ready resolution against a real held lock and a freshly published pointer,
  asserting holder identity, pointer identity, token, freshness, and window.
- Cover absence with no holder and no address.
- Cover each degraded reason against a real held lock: an unpublished pointer, corrupt
  pointer bytes, a portless payload, an hours-old heartbeat, and a payload naming another
  live process.
- Cover the legacy status-file fallback resolving an address when no singleton is held.
- Cover the refusal to fall back to the status file while a holder's own pointer is
  degraded, through both the typed resolver and the legacy port helper.
- Cover the rendered evidence naming the reason and both disagreeing identities.

## Outcome

Every resolution branch is now proven against real OS locks and real on-disk pointers,
including the previously untested distinction between a stopped machine and a live holder
that cannot be trusted to have published its address.

## Notes

The five pre-existing resolution tests were left untouched and still pass, so the typed
resolver is a compatible replacement rather than a parallel path. The corrupt-bytes case
accepts either the missing or the invalid reason: the tolerant pointer reader cannot
distinguish unreadable bytes from an absent file, and both refusals are degraded and
yield no address, so pinning one of the two would assert an implementation detail rather
than the contract.
