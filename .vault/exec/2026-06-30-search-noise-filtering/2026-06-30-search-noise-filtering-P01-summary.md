---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# `search-noise-filtering` `P01` summary

Foundation laid: one shared, worker-safe path-domain classifier and an
index-time `domain` payload that makes query-time filtering cheap, plus
exclusion of agent worktree clones from the index.

- Created: `src/vaultspec_rag/_domain.py`, `src/vaultspec_rag/tests/test_domain.py`
- Modified: `src/vaultspec_rag/search/_postprocess.py`,
  `src/vaultspec_rag/store.py`, `src/vaultspec_rag/store_schema.py`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py`,
  `src/vaultspec_rag/tests/test_indexer_unit.py`,
  `src/vaultspec_rag/tests/test_store_schema_parity.py`

## Description

`classify_domain(path)` is the single source of truth (prod / tests / docs /
locale / generated / vendored / worktree); `_classify_chunk_type` now projects
onto it for `--prefer`. The code chunk payload gains a path-derived `domain`
field, added to the code KEYWORD index set (additive - no schema-version bump);
`ensure_code_table` ensures the index even on existing collections so the field
backfills on reopen. `.claude/worktrees/` clones are excluded at scan time.
Verified by the classifier, payload-parity, and worktree-exclusion unit tests.
