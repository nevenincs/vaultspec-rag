---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S27'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# report torch CUDA availability as a readiness dimension without forcing model load

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Report torch CUDA availability as a readiness dimension by reading only torch's observable attributes (`torch.version.cuda` and `torch.cuda.is_available()`), never constructing or loading a model onto the GPU.
- Reuse the existing torch diagnosis classifier to map those attributes onto a `working` / `cpu_only` / `no_gpu` diagnosis, and translate that into a bounded readiness status with an actionable detail line for the non-ready cases.
- Carry the CUDA build, availability, diagnosis, and device name as structured `info` so a human render or JSON consumer surfaces them without re-deriving.

## Outcome

- The torch dimension reports `ready` with the real device name on the dev host (RTX 4080 SUPER) and degrades to `not_ready` with a reinstall remediation for the CPU-only and no-device cases. A no-model-load test asserts CUDA memory is unchanged across the computation.

## Notes

- Implemented in `src/vaultspec_rag/_readiness.py` (`_torch_readiness`), not directly in `api.py`; see S26 notes.
