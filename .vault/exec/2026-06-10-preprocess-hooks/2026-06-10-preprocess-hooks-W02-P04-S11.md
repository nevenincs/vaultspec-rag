---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S11'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for cache hit/miss, version-bump invalidation, and clean rebuild (D7)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_cache.py`

## Description

Added `test_preprocess_cache.py`: 7 tests over real `tmp_path` cache files - empty miss,
write-then-hit, different-source-hash miss, command-change (version-bump) invalidation,
corrupt-entry tolerance (treated as miss), clean-rebuild clearing plus already-absent
no-op, and a units+locator round-trip (D7).

## Outcome

7/7 pass; ruff clean. Covers hit/miss, invalidation, and clear acceptance points.

## Notes

Command-change test demonstrates the documented version-bump lever.
