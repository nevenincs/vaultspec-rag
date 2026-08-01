---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:a8d147c54e57505aecd95f2e40ff13c841fd06635023a85ffd17c2d70307199f'
step_id: 'S12'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# CPU transition-coordinator proof remediation

## Status

Satisfied by the focused registry recovery evidence landed in `bbf02d53` and reconciled source inspection. No test command was rerun during this acceptance review.

## Description

CPU-only registry proof uses real threads, the real manager persistence writer, a real service-loop thread, and a bound runner to demonstrate that same-ID recovery is durable before execution. It also covers fail-closed unpublished recovery, repaired concurrent retry, and one exact dispatch claim reaching one attempt.

## Outcome

The ordering case blocks the adopted service loop, observes the production queued desired-running attempt 2 on disk with the controller at the reopened epoch, and proves the runner has not started. Releasing the loop then drives canonical registry dispatch to one successful same-ID attempt. The repaired-retry case first produces a real unpublished filesystem failure in `warming`, repairs the directory, and drives two concurrent resume callers through one shared transition, one epoch increment, one dispatch-claim generation, and one attempt.

## Evidence

`bbf02d53` extends the focused registry test with a real event-loop owner, blocked callback rendezvous, production persisted-state reads, a bound recording runner, real concurrent resume threads, shared transition identity, exact epoch assertions, one claim-generation increment, an empty pending-claim map after dispatch, and one attempt-2 completion. This supplies the registry-owned ordering and repaired concurrent retry evidence that manager-cache and loopless-dispatch tests alone did not provide.

## Notes

A deterministic real post-publication directory-sync failure remains non-portable on Windows and is not manufactured. S11 and S14 own exhaustive typed published-not-durable propagation; S17 owns manager-level dispatch-token races. S16 and S18 are satisfied by the landed route mapping and closed-admission ownership proof, so this Step no longer blocks W02 completion. No service, RAG endpoint, CUDA allocation, GPU test, or CPU test was run in this reconciliation.
