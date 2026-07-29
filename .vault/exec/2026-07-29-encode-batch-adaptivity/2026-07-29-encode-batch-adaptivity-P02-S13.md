---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S13'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# extend degradation evidence assembly with encode budget, OOM count, and rate-baseline lines

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- extend `degradation_evidence` in `src/vaultspec_rag/jobs.py` with encode budget, OOM count, and rate-baseline lines, present only when the data exists
- carry one job's read-side facts as the frozen `DegradationInputs` dataclass, moving the production call site and direct test calls in the same commit

## Outcome

Commit `aa5f1aed`. Gates each exit 0; pytest 148 passed.

## Notes

The dataclass replaced a seventh positional argument rather than a lint suppression, matching the existing parameter-object convention.
