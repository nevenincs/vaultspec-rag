---
tags:
  - '#exec'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S02'
related:
  - "[[2026-07-24-index-cuda-shared-device-plan]]"
---

# change resolve_index_cuda_ceiling_mb to derive the absolute auto ceiling as min(baseline + free - headroom, total - headroom) with the operator override and profile fallback unchanged

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add a required `baseline_mb` keyword to `resolve_index_cuda_ceiling_mb` in `src/vaultspec_rag/memory_probe.py`.
- Derive the auto branch (configured_mb <= 0) as `max(0, min(baseline_mb + free - headroom_mb, total - headroom_mb))` - ABSOLUTE, inclusive of the resident models, because enforcement subtracts the baseline from both the captured peak and the ceiling; a bare `free - headroom` would charge the models twice and falsely reject legitimate forwards.
- Keep the fallback chain: free unavailable -> `total - headroom`; total unavailable -> profile figure.
- Keep the positive operator override authoritative and unchanged.

## Outcome

Auto ceiling tracks free device memory on a contended GPU and recovers `total - headroom` on an idle one; the docstring states the double-count constraint directly.

## Notes
