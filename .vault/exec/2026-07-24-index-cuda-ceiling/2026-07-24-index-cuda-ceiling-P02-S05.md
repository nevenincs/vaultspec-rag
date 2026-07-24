---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S05'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Added `resolve_index_cuda_ceiling_mb()`: a positive `configured_mb` is an
  authoritative bidirectional override; otherwise the ceiling is
  `device_total - headroom_mb`, falling back to the profile figure when the
  device total is unavailable.
- Added the `index_cuda_headroom_mb` default (2048) and its env var, and
  changed `index_cuda_ceiling_mb`'s default to `0` (auto-derive sentinel).
- Added `_finite_non_negative` so the ceiling knob admits its `0` sentinel.

## Outcome

The knob resolves 0 by default (auto) and honours a positive override; the
headroom knob resolves 2048 and rejects zero as before.

## Notes

The `index_cuda_ceiling_mb` knob changes meaning from an absolute cap to a
bidirectional override with a 0=auto sentinel. This is the operator-facing
semantic migration the ADR flagged for the changelog.
