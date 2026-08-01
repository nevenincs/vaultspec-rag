---
tags:
  - '#exec'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:adc96f66ff101b1e863e48cc1c9c247b87ab164daaa5832821a27b13684ae435'
step_id: 'S06'
related:
  - "[[2026-07-28-convergence-cost-plan]]"
---

# Update retry-state tests pinning the old escalation and add tests proving scoped retention plus every preserved escalation path

## Scope

- `src/vaultspec_rag/tests`

## Description

- Rewrite the interruption test to assert scoped retention plus fresh-instance promotion; add a success-with-mid-attempt-event scoped test.
- Update the cancelled-contended-admission test and the integration cancellation test to the retained-scope contract.
- Prove both retention guards can fail by restoring the forced escalation and watching each fail on its named assertion.

## Outcome

29 watcher-retry tests pass, including two new retention tests; recovery, failure, and cross-instance promotion assertions unchanged and still pass.

## Notes

None.
