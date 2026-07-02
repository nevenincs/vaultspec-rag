---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
step_id: 'S08'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Consume the schema index tuples in ensure_table and ensure_code_table instead of inline literals

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Replaced the inline KEYWORD/INTEGER field literals in `ensure_table` with iteration over `store_schema.VAULT_KEYWORD_INDEXES` and `VAULT_INTEGER_INDEXES`.
- Replaced the inline field literals in `ensure_code_table` with `store_schema.CODE_KEYWORD_INDEXES` and `CODE_INTEGER_INDEXES`, preserving the explanatory comments about node_type and the preprocessing locators.

## Outcome

The payload index sets are created from the single declared source; the P04 drift test asserts the live collection's indexed fields equal these tuples.

## Notes

None.
