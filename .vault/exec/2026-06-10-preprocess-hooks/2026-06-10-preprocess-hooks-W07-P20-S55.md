---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S55'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add passthrough end-to-end and indexer-level cache version-bump coverage (TST-002, TST-003)

## Scope

- `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`

## Description

Added two integration tests (real GPU + Qdrant): `test_passthrough_indexes_raw_text` - a
`.log` matched by a failing rule with `on_error=passthrough` is chunked as raw text and
found by search with `preprocessor_id` None (TST-002); and `test_command_change_reextracts`

- indexing with extractor "alpha" then bumping the command to extractor "beta" and clean
  rebuilding re-extracts so search finds the new content (TST-003, the cache command-lever).

## Outcome

Both pass; the preprocess integration suite is now 6/6 on real GPU.

## Notes

Closes the end-to-end coverage gaps the review flagged for passthrough and cache
invalidation.
