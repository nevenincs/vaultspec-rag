---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:030228314de85890d34e8deda30b3d2b852fecad0c1464b6473d952baa655b13'
step_id: 'S13'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# release the allocator cache immediately before rebasing peak counters so a job's peaks describe that job

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Call `empty_cache()` immediately before `reset_peak_memory_stats()` in `reset_cuda_peak_memory_stats` so the rebased peak counters describe the admitted job, not process retention history.

## Outcome

A job's recorded peaks start from genuinely retained memory; the reset means what its name implies.

## Notes

Landed in commit `29168706` (same authorization as the enforcement removal).
