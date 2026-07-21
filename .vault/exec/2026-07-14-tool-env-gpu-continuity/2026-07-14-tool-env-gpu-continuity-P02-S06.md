---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Add an optional phase field to the service status sidecar schema with writer and reader back-compat treating an absent phase as today's semantics

## Scope

- `src/vaultspec_rag/cli/_service_status.py`

## Description

- Define SERVICE_PHASE_WARMING / SERVICE_PHASE_RUNNING in `src/vaultspec_rag/serviceclient/_discovery.py` (the daemon writer must stay free of cli imports) and re-export them from `src/vaultspec_rag/cli/_service_status.py`.
- Add the tolerant `_service_phase` reader (absent, empty, or non-string phase reads as None - pre-phase semantics).

## Outcome

Committed as 4150505. Absent-phase back-compat covered by TestWarmingStatusState.

## Notes

The constants live one layer lower than the step's scoped file because the S07 writer (server domain) cannot import cli; the cli module re-exports so both surfaces share one vocabulary.
