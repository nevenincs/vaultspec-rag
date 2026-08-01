---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:af652f7dd09f5d3d7eb11d3f8902a9015ae3362f29bec437d208aa7059788f96'
step_id: 'S09'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Keep the main thread interruptible across blocking operator polls

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Run a blocking operator poll on a worker thread while the main thread waits in short interruptible sleeps.
- Carry any worker failure back to the caller rather than flattening it into an absent result.
- Exit the watch view on the conventional interrupted status instead of reporting success.

## Outcome

An interrupt is serviced in tens of milliseconds where it had been absorbed for the whole request timeout. Measured with a real console interrupt against an unresponsive daemon: 29.004 seconds before, 0.041 after.

## Notes

Nothing was swallowing the interrupt. An interrupt only becomes an exception at an interpreter check, and a thread parked in a socket read reaches none, which is why this presented as intermittent: against a healthy daemon the poll takes milliseconds and the loop sits in the interruptible sleep. The wait is a sleep loop over a non-blocking check rather than a timed event wait, which would reintroduce the defect. One helper serves both the watch loop and the start wait, so the two operator views cannot diverge.
