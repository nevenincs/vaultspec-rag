---
tags:
  - '#exec'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:4b716e34dac76035d74b3b3d80912811185bd3c4f0421552ada9d20f1ab4fd1b'
step_id: 'S02'
related:
  - "[[2026-08-14-gpu-admission-unreadable-plan]]"
---

# Route the probed and the supplied reading through one judgement so neither bypasses the ledger

## Scope

- `src/vaultspec_rag/_gpu_admission.py`
- `conftest.py`

## Description

- Collapse the two admission call sites onto one judgement that brings
  together the three inputs a verdict needs: the reading, the configured
  floor, and the running streak.
- Point the probed path and the supplied-reading path at it, so neither
  can be judged by rules the other does not use.
- Follow the renderer rename through to the pytest GPU preflight, which is
  the only consumer outside the gate and its suite.

## Outcome

No reading reaches a verdict without passing through the ledger. This was
the load-bearing half: the supplied-reading path exists so the window's
real behaviour stays exercisable, and had it skipped the ledger, every
guard written against it would have been exercising a predicate that
production never runs.

## Notes

The renderer was renamed rather than joined by a second one. Its name said
contention while it now renders two refusals, only one of which is about
contention, and an alias kept for the old name would have been the drift
the canonical-code rule forbids.
