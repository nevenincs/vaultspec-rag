---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S08'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Verify deleted records self-heal and shutdown cannot resurrect discovery after cleanup

## Scope

- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`

## Description

- Add a real-daemon regression proving each discovery view repairs on the next
  heartbeat after deletion, and that repairing one view never removes the other.
- Add a real-daemon regression proving owner cleanup is terminal: after a clean stop
  neither view returns across a full heartbeat interval.
- Nest the isolated managed storage one level below the session temp root so the
  machine pointer and the status view resolve to distinct paths, as they do in
  production.
- Fund a real graceful drain window on the operator stop path so the daemon completes
  its own owner-authenticated cleanup before any forced-kill escalation.

## Outcome

Both discovery views are now proven to self-heal independently under a live isolated
daemon, and a clean stop is proven to leave neither view behind or recreate it. The
operator stop path no longer strands a machine pointer advertising a dead process.

## Notes

The integration environment previously pointed the status directory and the managed
storage parent at the same temp directory, so both discovery views collapsed onto one
file. Every independent-repair and independent-cleanup assertion was vacuous under that
layout, and it masked a real defect: only the daemon holds the machine-lock lease that
authorises deleting the machine pointer, but the stop path escalated to a forced kill
about two seconds after signalling, well before a daemon carrying GPU stores and a
managed Qdrant child can drain. Every stop therefore removed the status view through the
CLI while orphaning the pointer. Separating the two paths surfaced the defect
immediately; the stop path now funds a drain window and falls back to the forced kill
only once that window expires.

Verification of the two new regressions contended with a concurrently running GPU
integration suite in the shared worktree; the focused run was repeated once the device
was free rather than treated as a flake.
