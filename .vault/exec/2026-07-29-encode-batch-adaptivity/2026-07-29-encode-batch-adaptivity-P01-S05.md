---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S05'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# move the GPU-lock bracket from the whole-slice encode to per-bucket forward holds in the slice vector-field encoder

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- pass the GPU lock through `encode_documents_on_device` so the per-bucket `timed_gpu_lock` holds become live, and remove the outer whole-slice lock hold in `_encode_slice_vector_fields` in the same commit
- drop the now-unused `timed_gpu_lock` import from `src/vaultspec_rag/indexer/_streaming.py`

## Outcome

Commit `e975d84a`. Gates each exit 0; pytest 79 passed across the gate files plus the slice-writer, index-reuse, consumer-progress, and jobs-degradation suites. No commit boundary has a double bracket or a missing bracket; sparse bracketing verified unchanged (one forward per hold, transfer and conversion outside).

## Notes

Seam-imposed mechanical fixes (a `gpu_lock` parameter on encoder doubles) rode along in five test files, including `src/vaultspec_rag/tests/test_jobs_degradation.py`, which belongs to the telemetry lane; no behavior or assertion content changed there. The cross-lane merge was verified conflict-free.
