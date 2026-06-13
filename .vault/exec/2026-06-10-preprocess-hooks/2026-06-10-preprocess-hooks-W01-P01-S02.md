---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S02'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Resolve rules per-root via a new \_build_preprocess_rules() in the codebase indexer (D1, D2)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Added `_build_preprocess_rules()` to `CodebaseIndexer`, placed beside
`_build_vaultragignore_spec` and resolving `.vaultragpreprocess.toml` fresh from
`self.root_dir` on each call (root-only, no subtree walk) so an edited config is picked up
on the next scan (D1, D2). Imported `PreprocessConfig` / `load_preprocess_rules`.

## Outcome

Per-root resolution wired; indexer imports cleanly. Gate/worker consumption lands in W03.

## Notes

No instance caching, mirroring the `.vaultragignore` re-read-per-scan semantics.
