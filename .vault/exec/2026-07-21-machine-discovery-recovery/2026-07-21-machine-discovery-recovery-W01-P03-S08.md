---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c7d35057b7cad4580ce023b16fb363089fba25aad9c550822ce096a5ced1424f'
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
- Fund a graceful drain window on the operator stop path only where the termination
  signal can actually be delivered, and keep the short escalation everywhere else.
- Reclaim the freed machine singleton after the holder is confirmed gone and delete the
  discovery pointer it left behind, under a genuinely held lease.

## Outcome

Both discovery views are now proven to self-heal independently under a live isolated
daemon, and a clean stop is proven to leave neither view behind or recreate it. The
operator stop path no longer strands a machine pointer advertising a dead process.

## Notes

The integration environment previously pointed the status directory and the managed
storage parent at the same temp directory, so both discovery views collapsed onto one
file. Every independent-repair and independent-cleanup assertion was vacuous under that
layout, and it masked a real defect: only the daemon holds the lease that authorises
deleting the machine pointer, so every stop removed the status view through the CLI while
orphaning the pointer.

The first fix attempt was wrong and the regression caught it. Funding a long drain before
the forced kill assumed the daemon could act on the termination signal; it cannot on
Windows, because the daemon is spawned console-detached and a console control event only
reaches processes sharing the sender's console. The drain bought latency and nothing else,
and the regression still failed. The drain is therefore now spent only on platforms that
deliver the signal, where the daemon really does clean up after itself.

The general fix inverts the ownership problem instead of waiting on it: once the holder is
confirmed dead the operating system has released the singleton, so the stop path acquires
it and deletes the stranded pointer as the momentary owner. That satisfies the
owner-authenticated deletion contract rather than bypassing it, and a failure to acquire
means a successor already owns the singleton, whose pointer must not be touched.

Verification contended with a concurrently running GPU integration suite in the shared
worktree; the focused run was repeated once the device was free rather than treated as a
flake.
