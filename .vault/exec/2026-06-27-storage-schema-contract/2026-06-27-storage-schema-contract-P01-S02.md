---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:ba402229423454fb52b287f2b40897a4b5218899288a03cf3df7b4a464576e43'
step_id: 'S02'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Declare the canonical KEYWORD and INTEGER payload-index field tuples per collection

## Scope

- `src/vaultspec_rag/store_schema.py`

## Description

- Declared `VAULT_KEYWORD_INDEXES` / `VAULT_INTEGER_INDEXES` and `CODE_KEYWORD_INDEXES` / `CODE_INTEGER_INDEXES` as the canonical per-collection index tuples.
- Matched the tuples field-for-field to the index sets currently created in `ensure_table` and `ensure_code_table`.

## Outcome

The index sets are declared once in the schema module; P02.S08 routes `ensure_table`/`ensure_code_table` to consume them, and the P04 drift test asserts the live collection's indexed fields equal these tuples.

## Notes

None.
