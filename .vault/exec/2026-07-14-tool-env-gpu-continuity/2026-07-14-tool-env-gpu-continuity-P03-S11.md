---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:c6a76548580b0e3f91307bd4b0fab2a84a3adfc0d7cd1b24aa483b32977b8525'
step_id: 'S11'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Assert the jobs human summary carries the --json signpost and that the jobs --json envelope shape is unchanged

## Scope

- `src/vaultspec_rag/tests/test_jobs_unit.py`

## Description

- Add TestJobsHumanSummarySignpost to `src/vaultspec_rag/tests/test_jobs_unit.py`: the rendered feed carries the --json signpost next to the always-present state words, and the --json help warns about scripted waits.

## Outcome

Committed as 0616f5f. 2 passed.

## Notes

The envelope-shape-unchanged claim is carried by the existing jobs --json coverage in the integration suite; no new envelope test was needed because the envelope emitter was not touched.
