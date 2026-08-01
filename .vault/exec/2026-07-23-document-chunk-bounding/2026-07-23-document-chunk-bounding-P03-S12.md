---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:b007dfc6e15564d8ba38473541f1fe5ab43e460d083aa464c3141a834c3c52d2'
step_id: 'S12'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# keep sampling and reporting reserved on job resilience records and metrics as a diagnostic

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Keep reserved sampled on every budget snapshot (`cuda_reserved_mb`, `peak_cuda_reserved_mb`) and reported on job resilience records, `server jobs` rendering, and metrics.

## Outcome

Reserved remains the honest operator signal for fragmentation and device pressure; it no longer decides job outcome. Verified by the resilience-record field tests staying green unchanged.

## Notes

No code change was needed beyond the enforcement removal - the reporting surfaces already carried the field; this step verified none of them was severed.
