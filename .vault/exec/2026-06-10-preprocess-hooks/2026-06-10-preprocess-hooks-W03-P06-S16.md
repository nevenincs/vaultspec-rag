---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S16'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Make the scoped incremental gate preprocess-rule-aware (D2, D8, D10)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Reworked `_process_changed_path` (scoped/incremental path) so a preprocess-rule match makes
the file indexable regardless of extension/size/binary, mirroring the full-scan gate
(D2, D8, D10). A previously-indexed file that becomes non-indexable and is unmatched is
still queued for deletion. Ignore is applied first and wins.

## Outcome

Watcher/incremental edits to matched binaries route to hashing+chunking; unmatched
behaviour preserved.

## Notes

Shares the `_matches_preprocess_rule` helper with the full-scan gate.
