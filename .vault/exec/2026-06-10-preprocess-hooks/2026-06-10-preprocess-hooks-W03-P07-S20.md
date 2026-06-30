---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S20'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for collection upsert, the locator-index split, and purge-by-path (D12)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_store.py`

## Description

Added `test_preprocess_store.py` (4 tests) against a real local Qdrant (embedding_dim=4,
dummy vectors, no GPU/model, no mocks): int-locator payload persists (page/value_int,
value_str null), str-locator payload persists (sheet/value_str, value_int null), purge by
source path returns both unit chunks of a source, and an ordinary code chunk carries null
preproc fields (D12).

## Outcome

4/4 pass. Confirms the split-locator payload and source-path reconciliation.

## Notes

Marked `unit` - real Qdrant local mode is CPU-only and runnable in the unit gate.
