---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S52'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Carry Locator.end through the chunk payload, CodeChunk, and result rendering (PREPROCESS-005)

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

Carried `Locator.end` through: added `locator_end_int`/`locator_end_str` to `CodeChunk` and
the code payload; extracted a `_split_locator_value` helper in the worker reused for both
`value` and `end`; and taught `_format_locator` to render a range (`page 1-3`) when an end
component is present (PREPROCESS-005).

## Outcome

Range locators now persist and render instead of being silently dropped at the chunk seam.

## Notes

End fields are unindexed (diagnostic/display only), like the rest of the locator payload.
