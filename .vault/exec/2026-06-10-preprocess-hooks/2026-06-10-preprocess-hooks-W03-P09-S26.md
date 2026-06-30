---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S26'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add anchor and locator to the pydantic SearchResultItem wire model (D12)

## Scope

- `src/vaultspec_rag/server/_models.py`

## Description

Added the same four fields to the pydantic `SearchResultItem` wire model (MCP/HTTP). Since
it sets `from_attributes=True`, the fields auto-populate from `SearchResult`, so MCP
`search_codebase` results now expose anchor/locator/source_path/preprocessor_id (D12).

## Outcome

MCP search responses carry the preproc deep-link fields; backward-compatible (all optional,
default None).

## Notes

No mapper change needed beyond the SearchResult fields from S25.
