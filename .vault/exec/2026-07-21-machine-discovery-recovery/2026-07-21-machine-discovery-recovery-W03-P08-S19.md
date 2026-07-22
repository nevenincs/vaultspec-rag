---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S19'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Implement bounded owner-driven reconcile over repeated typed resolution and identity-confirmed health

## Scope

- `src/vaultspec_rag/serviceclient/_status.py`

## Description

- Define the reconcile outcome vocabulary, its bounded defaults, and a structured result
  carrying the attempt count, elapsed time, final verdict, and detail.
- Poll typed resolution and composed status until the verdict is running and the serving
  daemon's identity is confirmed against the pointer's own token and process.
- Return immediately when no singleton is held, and report unresolved on the bound.

## Outcome

An operator surface can now wait for owner-published discovery to converge, bounded, and
report exactly what it observed rather than guessing whether a retry would help.

## Notes

Convergence requires identity agreement, not merely a reachable port. A service answering
on the advertised address is only the right service when its own token and process match
what the owner published; accepting reachability alone would let reconcile declare success
against a foreign daemon that happens to hold the port.

Reconcile writes nothing. Only the singleton owner may publish or delete its pointer, so
the sole correct repair is that owner's next heartbeat. Polling for it, rather than
repairing on the owner's behalf, is what makes the verb safe to run against a healthy
machine.
