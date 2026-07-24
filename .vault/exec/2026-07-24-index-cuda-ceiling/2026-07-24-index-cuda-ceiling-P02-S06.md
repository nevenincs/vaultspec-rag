---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling

## Scope

- `src/vaultspec_rag/job_dispatch.py`

## Description

- Replaced the one-way `min(profile, config)` clamp in `_admitted_resilience`
  (the pre-model admission snapshot) with `resolve_index_cuda_ceiling_mb`.

## Outcome

Admission now projects the derived or overridden ceiling. On the daemon torch
is resident, so the device query succeeds here too; off-GPU it falls back to
the profile figure.

## Notes

None.
