---
tags:
  - '#exec'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-operator-feedback-hardening-plan]]"
---

# Complete the start wait when the daemon can serve, not on the ready word

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Gate the wait on whether the daemon can serve, read from the models-resident and backend-live fields.
- Carry the degradation reasons into both the human lines and the machine envelope when a serving daemon reports itself degraded.
- Name the last published phase in the timeout message instead of reporting a bare not-ready.

## Outcome

A serving-but-degraded daemon completes the start instead of consuming the full deadline. Verified against a real cold start at 44.9 seconds, where the previous behaviour was a 300-second refusal.

## Notes

Guard proof recorded: restoring the strict status comparison fails the regression test on the intended assertion. The verdict reads structured fields rather than the prose reason list, because that list is display text. The attach path had always treated a degraded daemon as an attachable success, so this also removes a disagreement between two paths about one state.
