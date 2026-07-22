---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S03'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Upgrade memory observation into an enforceable RSS and CUDA budget sampled outside gpu_lock

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Add immutable RSS and CUDA admission ceilings with immutable current and peak snapshots.
- Sample enforcing measurements outside `gpu_lock` without importing heavy model modules.
- Fail closed with typed outcomes when a configured measurement is unavailable or exceeded.
- Latch the first violating observation atomically so concurrent work cannot continue.
- Preserve the legacy optional observation probe and its zero-fallback compatibility.

## Outcome

Index pipelines can now enforce admitted process and device-memory ceilings at explicit safe
checkpoints. Exact-threshold readings remain valid, RSS wins simultaneous classification,
both CUDA allocated and reserved memory are bounded, and every caller observes the same first
terminal failure once the budget trips.

## Notes

Independent review found three High defects in the first revision: admitted ceilings could be
mutated, unavailable enforcing measurements could silently read as zero, and a concurrent
observation could overwrite a violating snapshot and return success. The final revision makes
all enforcement state read-only to ordinary mutation, separates strict samplers from legacy
observers, and classifies and latches the first failure under one lock.

Final review found no unresolved findings at any severity. Direct threshold, unavailable,
legacy, import-light, and live-sampler probes passed; a 32-thread race produced one identical
latched failure for every post-breach caller. Six focused real tests, Ruff, ty, BasedPyright,
and diff checks passed. No model forward was run.
