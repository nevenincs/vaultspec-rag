---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S05'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Bound job-history degradation to the current service generation

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Stamp a wall-clock generation start alongside the existing monotonic one.
- Append a job-failure degradation reason only for a failure that finished within the current generation.
- Leave the failure record itself in the payload, and leave the stalled-job branch unconditional.

## Outcome

A failure inherited from an earlier process no longer lowers the current service's status, while remaining visible and reportable. Verified live: a new daemon reported ready with historical failures still on file.

## Notes

The generation instant is the earlier of a recorded stamp and one derived from the monotonic clock, so a clock adjustment can only widen the window a job is judged against. Widening at worst reproduces the previous over-reporting, which is visible and self-clearing; narrowing would hide a live failure. An untimestamped failure still degrades, biased toward reporting.
