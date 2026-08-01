---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:824e11e177b432da930c1aaaa142f7ee6f6479ee7e2b092cbdf5367d884d775b'
step_id: 'S14'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# render the encode budget, OOM, and rate-baseline evidence in the jobs presentation and TUI detail

## Scope

- `src/vaultspec_rag/cli/_service_jobs_presentation.py`

## Description

- render the encode budget, OOM, and rate-baseline evidence verbatim from the service payload in `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- append the throughput phrase to the unhealthy row summary so a rate-collapse verdict names its cause instead of a fresh progress stamp

## Outcome

Commit `dff41f25`. Gates each exit 0; pytest 112 passed.

## Notes

No CLI-side verdict computation; existing wording and thresholds unchanged.
