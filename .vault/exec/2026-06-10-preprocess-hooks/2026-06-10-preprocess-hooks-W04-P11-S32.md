---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S32'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Bump the SUPPORTED_EXTENSIONS test floor and add positive map assertions (D13)

## Scope

- `src/vaultspec_rag/tests/test_indexer_unit.py`

## Description

Bumped the `test_all_extensions_count` floor from `>= 25` to `>= 29` and added positive
assertions `LANGUAGE_MAP[".txt"]==("text",None)`, `.properties`, `.xml`, `.xsd` in
`test_indexer_unit.py` (D13).

## Outcome

The new extensions are locked in by tests; the existing bijective-consistency test passes
as-is.

## Notes

Floor now guards regressions on the four additions.
