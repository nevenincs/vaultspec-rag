---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-02'
step_id: 'S05'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Decouple a code-path encode batch size in config with a higher default and throttle the per-slice empty_cache to a periodic flush

## Scope

- `src/vaultspec_rag/config.py`

## Description

- Add a decoupled code-path encode batch size (default 32) and throttle the per-slice CUDA cache flush to every N slices.

## Outcome

Larger inner encode batch for short uniform code chunks; most per-slice device syncs removed while allocator growth stays bounded.

## Notes

None.
