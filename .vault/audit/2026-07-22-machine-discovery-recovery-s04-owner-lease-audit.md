---
tags:
  - '#audit'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:15496e10000755b0362832a3d563153a5d8bb3ff78e62ed5709a972e26f1c6f6'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# `machine-discovery-recovery` audit: `W01.P02.S04 retained owner lease`

## Scope

Safety, intent, and quality review of the retained machine-lock capability and the
owner-authenticated pointer mutation primitives against ADR decisions D1 and D6.

## Findings

No critical, high, medium, or low findings remain. Publication and deletion require object
identity with the module-retained lease, current-process PID agreement, and an open retained
descriptor. A caller cannot gain authority by copying PID or lock-file data, constructing a
lookalike lease, retaining a released lease, or inheriting the capability across a fork.

The payload PID is exact-integer checked against the lease owner before mutation. JSON
serialization completes before a unique temporary file is created, the temporary file is
flushed and fsynced, and `os.replace` exposes the completed document atomically. Cleanup
removes only the operation's unique temporary file. Lease release and pointer mutation share
one process lock, eliminating a check-then-release race.

The pytest containment guard covers both the lease path and derived pointer path before every
new effect. Existing bool acquisition remains only as the currently consumed entry point;
the approved lifecycle phase threads the explicit lease through daemon startup and shutdown.

Status: **PASS**. Direct adversarial real-process proof remains assigned to Step S05 and no
lifecycle migration is claimed by this Step.

## Recommendations

Proceed to S05 and prove that a real foreign holder leaves a sentinel pointer unchanged while
stale non-owner publication and deletion fail, then prove a newly retained owner succeeds.
