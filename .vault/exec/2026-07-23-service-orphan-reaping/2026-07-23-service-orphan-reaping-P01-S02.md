---
tags:
  - '#exec'
  - '#service-orphan-reaping'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S02'
related:
  - "[[2026-07-23-service-orphan-reaping-plan]]"
  - "[[2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference]]"
---

# Reproduce a race-losing daemon in an isolated sandbox and capture the launcher-daemon process tree, persisting the pair-origin confirmation

## Scope

- `.vault/reference/2026-07-24-service-orphan-reaping-launcher-daemon-pair-reference.md`

## Description

- Build a probe that creates a temp sandbox and points the status dir, the
  Qdrant storage dir, and the Qdrant port at it before any config resolution,
  so the machine lock and the machine discovery pointer relocate with it.
- Acquire the isolated machine-lock lease in the probe, guaranteeing the
  spawned daemon loses the singleton race rather than racing for it.
- Spawn the daemon through the CLI's own resolved interpreter, detached, on an
  ephemeral service port.
- Capture the process tree by walking the spawned launcher's own child list -
  the first attempt sampled with a global command-line sweep and saw nothing,
  because that sweep costs longer than the daemon lives.
- Time one production orphan enumeration cold and warm, and record what a
  sweep of that duration can and cannot observe.
- Persist the confirmation, the mechanism, and the enumeration bound to a
  reference document.

## Outcome

The pair is confirmed and its mechanism named. One spawn produces two
witness-carrying processes in a parent-child relation: the venv `python.exe`
launcher and the real uv-managed interpreter it re-execs, sharing a
byte-identical command line 13 milliseconds apart, exiting together with the
worker's code propagated. A third descendant, a console host, carries no witness
and is not a daemon - recorded so "the daemon is two of the three" is measured
rather than assumed. The loser published no pointer, no status view, no
listener, and no Qdrant child, and its log carries the forced-exit witness line
that only the backstop writes.

The second finding is a bound rather than a defect: one enumeration costs about
39 seconds cold and 4 to 6 warm on a host with roughly a thousand processes,
essentially all of it reading command lines. A sweep is therefore not a
snapshot - a process that exits mid-walk is dropped - but the reap's safety
anchors are computed outside the sweep, so a degraded sweep can only miss an
orphan, never kill the singleton.

## Notes

Measured on Windows only. The pair is a venv-shim artefact; on POSIX the spawn
is a single process, which is why the suite's expected witness count per daemon
is platform-conditional. The enumeration cost is recorded as a constraint on
what the reap can observe, not addressed here - narrowing that sweep is outside
this plan's scope and is carried into the closing review as a follow-up.
