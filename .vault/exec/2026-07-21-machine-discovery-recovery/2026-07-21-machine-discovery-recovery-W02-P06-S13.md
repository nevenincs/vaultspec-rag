---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:de89f0b4298dd8a1ae8d47d0321fc7704a9b1e4284ce90072ff10a1e0889f649'
step_id: 'S13'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Define the canonical discovery status and health-composition model shared by operator adapters

## Scope

- `src/vaultspec_rag/serviceclient/_status.py`

## Description

- Define the canonical operator state vocabulary, including a degraded-discovery state
  distinct from both stopped and crashed.
- Define a record carrying the verdict, its label, its exit code, the typed resolution
  behind it, the probed liveness facts, and any health composition.
- Compose the verdict as a pure function of a typed resolution plus already-probed
  liveness signals, reporting degraded discovery before any liveness reasoning.
- Render the shared JSON body, including the discovery evidence, once for every adapter.

## Outcome

Operator surfaces now have one place to derive a verdict from, so status and doctor can
agree by construction rather than by keeping two derivations in step.

## Notes

Degraded discovery rides the established fault exit code rather than introducing a new
one: the exit contract is broker-facing, and a new code would have to be learned by every
supervising broker for a condition the state string and evidence already describe.

Composition is a pure function over supplied liveness facts rather than a probing routine.
Probing a process identifier and a socket is platform work owned by the process layer, and
keeping it out of this module is what lets the shared surface stay import-light and free
of any dependency on the command-line package.
