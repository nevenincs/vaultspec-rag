---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
body_hash: 'sha256:ba30b167a8c193968a648efa6e21beff0ee818c6efed7a67da867f43f254d178'
step_id: 'S53'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add a unit test asserting a range locator end persists and renders (PREPROCESS-005)

## Scope

- `src/vaultspec_rag/tests/test_preprocess_store.py`

## Description

Added `test_range_locator_end_persists`: a chunk with `locator_value_int=10` and
`locator_end_int=20` upserts and the payload round-trips both (PREPROCESS-005).

## Outcome

Passes against real local Qdrant; confirms the end component persists.

## Notes

Complements the render-side coverage in the search/locator formatting.
