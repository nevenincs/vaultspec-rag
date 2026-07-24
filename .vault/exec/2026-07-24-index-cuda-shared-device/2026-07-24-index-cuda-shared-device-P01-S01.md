---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# add a guarded cuda_free_memory_mb probe returning mem_get_info free in MiB or None off the GPU path

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add `cuda_free_memory_mb()` to `src/vaultspec_rag/memory_probe.py`, returning `torch.cuda.mem_get_info()[0]` converted to MiB.
- Mirror the guarded `cuda_device_total_mb` pattern exactly: shared cached module probe via `_measure_cuda_mb()`, `None` on torch-absent or CPU-only hosts, `None` on `RuntimeError`/`AssertionError` from the device call.

## Outcome

Guarded free-memory probe available to the ceiling derivation; off the GPU compute path it degrades to `None` and never forces torch onto service-client or worker paths.

## Notes
