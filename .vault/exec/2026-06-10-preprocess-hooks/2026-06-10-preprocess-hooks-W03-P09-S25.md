---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S25'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add anchor and locator fields to SearchResult and populate them at the codebase-result mapping seam (D12)

## Scope

- `src/vaultspec_rag/search/_models.py`

## Description

Added `source_path`, `preprocessor_id`, `anchor`, and `locator` to the `SearchResult`
dataclass, populated in `_map_codebase_results` from the chunk payload. A module-level
`_format_locator()` renders the split payload locator into a readable string (e.g.
`"page 12"`, `"sheet Summary"`) (D12).

## Outcome

Codebase search results now carry deep-link anchor + human locator for preproc hits; null
for ordinary code.

## Notes

Payload is already retrieved `with_payload=True`, so no query change was needed.
