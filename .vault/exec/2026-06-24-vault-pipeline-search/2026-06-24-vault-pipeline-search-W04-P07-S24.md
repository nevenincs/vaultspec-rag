---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S24'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Render the frontmatter metadata line with doc_type, feature, status, date, related

## Scope

- `src/vaultspec_rag/cli/_render.py`

## Description

- Added `_search_result_meta_line` to the renderer: for vault results it builds a single
  line with doc_type, feature, status, date, and up to five related stems; it returns None
  for codebase results (no doc_type), so only vault hits gain the line.
- Emitted the metadata line in `_display_search_results` between the location line and the
  body text.

## Outcome

Vault hits now show their pipeline context (notably status, so a superseded ADR is visible,
and the related lineage edges). Verified: an accepted ADR renders type/feature/status/date/
related; an exec with empty status omits the status segment; a codebase result gets no line.
JSON output already carries the fields via `asdict`. `ruff` and `ty` pass.

## Notes

Related stems are capped at five with an ellipsis to keep the line readable. No blockers.
