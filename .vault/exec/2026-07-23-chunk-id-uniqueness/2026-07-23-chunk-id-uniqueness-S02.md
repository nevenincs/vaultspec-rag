---
tags:
  - '#exec'
  - '#chunk-id-uniqueness'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:6fef06e6f9618085766ed5fdf12b5cd1a3df5c0d86c9163151898c5d926d66d1'
step_id: 'S02'
related:
  - "[[2026-07-23-chunk-id-uniqueness-plan]]"
---

# Add the same per-file emit ordinal discriminator to the text-splitter fallback chunk identifier

## Scope

- `src/vaultspec_rag/indexer/_chunk_worker.py`

## Description

- Changed the text-splitter loop in `chunk_with_splitter` to `enumerate` its text chunks, binding the per-file emit ordinal as `index`.
- Inserted `index` into the identifier as `f"{rel_path}:{index}:{line_start}-{line_end}:{chunk_hash}"`, matching the AST path from S01.
- Added a comment cross-referencing the AST path's rationale.

## Outcome

The non-AST fallback path (used for languages without a tree-sitter grammar) now also emits unique identifiers. This path collided the same way as the AST path: `content.find` advances its search offset past a repeated block, but the recomputed line span is identical for a no-newline line and the text is identical, so the pre-fix identifier collided. Both non-preprocess construction sites now carry the ordinal, matching the preprocess path's existing convention, so all three code-chunk construction paths are consistent.

## Notes

None.
