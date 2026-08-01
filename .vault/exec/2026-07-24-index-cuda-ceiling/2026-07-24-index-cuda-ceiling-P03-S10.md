---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:a0bf8015821e96da277baf1026b47e2811ef54218e46ac80dc5d06ca13b87c7a'
step_id: 'S10'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# add a bare peak reset-and-read helper that resets peak stats without flushing the allocator cache

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add `_reset_cuda_peak_stats_bare` to `src/vaultspec_rag/memory_probe.py`: rebases the allocator peak counters without `empty_cache`, because the per-forward capture bracket runs inside the GPU-lock hold and a cache flush there would add a device synchronisation per encode sub-batch.
- Add `_read_cuda_peak_allocated_mb` as the single sanctioned reader of the process-global peak counter, meaningful only inside the bracket that just rebased it.
- Refresh the `reset_cuda_peak_memory_stats` docstring: the per-run reset is now allocator hygiene at admission; enforcement no longer consumes the process-global counters.

## Outcome

Bare reset and read helpers exist alongside the throttled per-run reset; guarded probes return `False`/`None` off the GPU path so CPU-only hosts degrade silently.

## Notes

None.
