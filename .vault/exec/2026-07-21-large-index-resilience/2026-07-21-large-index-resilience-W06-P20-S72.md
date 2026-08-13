---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-08-13'
modified: '2026-08-13'
body_schema: 'body-v1'
body_hash: 'sha256:b79da37a893308023edf9c4e9a734e3aef71d2e6cd11796258ea6a7b9751b420'
step_id: 'S72'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Split the GPU runner into two sequential selections so the subprocess tier never shares a card with a resident-model tier

## Scope

- `justfile`

## Description

- Read the marker vocabulary's own statement that the subprocess tier must not co-schedule with the resident tiers, and found the project's GPU recipe selecting both in one expression.
- Split the recipe into two sequential selections: the resident tiers excluding the subprocess tier, then the subprocess tier alone.
- Made the second selection conditional on the first, so a failure in the resident lane still stops the run.

## Outcome

The runner no longer asks one session to hold both tiers. Confirmed by running the subprocess selection alone on a quiet machine: 67 passed, and the test that had been failing passed in 14.6 seconds against the 90-second health-poll timeout it hit when co-scheduled.

## Notes

The failure had been recorded as order-dependent, which it was not. It was a resource conflict whose only visible symptom was a spawned service that never became healthy - naming nothing about memory, and landing on whichever test happened to run late in the lane. That is why it survived several passes of triage.
