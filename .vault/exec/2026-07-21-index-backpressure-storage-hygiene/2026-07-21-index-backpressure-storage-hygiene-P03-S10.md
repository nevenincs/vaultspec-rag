---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S10'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# wire the same preflight into the in-process CLI index fallback with a single structured non-zero envelope in --json mode

## Scope

- `src/vaultspec_rag/cli/_index.py`

## Description

Verification found a real gap: `InsufficientDiskSpaceError` subclasses
`RuntimeError`, so the in-process CLI index path routed a preflight
refusal into `_handle_gpu_error` and misdiagnosed it as a torch problem.
Added an explicit except branch ahead of the GPU handler emitting exactly
one `disk_preflight_failed` envelope (`--json`) with storage remediation,
or a plain error line in human mode; exit 1 on both.

## Outcome

Committed as `fix(cli): disk-preflight refusal is a structured envelope,
not a GPU misdiagnosis (#242)`; `TestDiskPreflightRefusal` (json + human)
green.

## Notes
