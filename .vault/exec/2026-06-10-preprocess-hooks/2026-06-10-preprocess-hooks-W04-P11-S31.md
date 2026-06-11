---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S31'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add the .txt, .xml, .xsd, and .properties entries to LANGUAGE_MAP (D13)

## Scope

- `src/vaultspec_rag/indexer/_chunking.py`

## Description

Added `.txt`, `.properties` (label `text`) and `.xml`, `.xsd` (label `xml`) to
`LANGUAGE_MAP`, all with grammar `None` so they flow through the `TextSplitter`.
`SUPPORTED_EXTENSIONS` derives from the map, so the set picks them up automatically (D13).

## Outcome

These plain-text/markup tails now index first-class; `_is_binary` accepts them and the
splitter handles the unmapped `xml` label via its text-separator default.

## Notes

`.html` was already mapped; XML keeps a distinct label so it stays queryable as
`lang:xml`.
