---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:f88707d742b7d4ea27d9ccae0fc55456fa7127b1b5189f1d8bf3e84c41e853d9'
step_id: 'S07'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# replace the one-way min-clamp in the codebase indexer budget builder with the derived ceiling

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Replaced the min-clamp in the codebase indexer's `_begin_memory_budget`
  with `resolve_index_cuda_ceiling_mb`; the rss clamp is unchanged.

## Outcome

The enforcing code-index budget now carries the derived/overridden ceiling.
The `limits is None` fallback passes the config value as the profile figure,
but the ceiling is only enforced when `uses_cuda`, where the device query
always succeeds, so that fallback never enforces a degenerate value.

## Notes

None.
