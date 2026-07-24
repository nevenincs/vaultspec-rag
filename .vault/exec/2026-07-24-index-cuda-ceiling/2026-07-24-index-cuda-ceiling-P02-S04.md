---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths

## Scope

- `src/vaultspec_rag/_gpu.py`

## Description

- Added `cuda_device_total_mb()` to `memory_probe.py`: a guarded probe that
  returns the active device's total VRAM in MiB, or `None` on a torch-absent
  or CPU-only host, sharing the cached module guard with `_measure_cuda_mb`.

## Outcome

The live probe returns `16375.5` MiB on this box, so the auto-derived ceiling
resolves to ~14327 MiB (total minus the 2048 MiB headroom).

## Notes

**Deviation from the plan.** The Step scope names `_gpu.py`, but the probe was
placed in `memory_probe.py` instead. `_gpu.py` is the hard GPU gate whose
`load_torch` deliberately RAISES on a CPU-only host; a soft probe that must
return `None` there contradicts that contract, while `memory_probe.py` already
houses the guarded `None`-returning CUDA probes this one mirrors. The behaviour
and the torch-gating the ADR required are unchanged; only the file differs.
