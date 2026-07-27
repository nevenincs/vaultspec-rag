---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# `archive-restore-contract` `P01` summary

- Modified: `src/vaultspec_rag/storage_reclamation.py`
- Modified: `src/vaultspec_rag/tests/test_storage_ops.py`
- Modified: `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- Created: execution records for `P01.S03`, `P01.S04`, and `P01.S05`.

## Description

P01 completes archive-retention safety. Archive cleanup now retains or evicts every completed namespace directory as one restore unit, so a byte cap cannot preserve a manifest after deleting its snapshots. Completed archives re-read their persisted manifest before return, verify every referenced snapshot is present and nonempty, and require each recorded pre-snapshot point count to still match the live collection.

The guard suite uses real filesystem artifacts and a live Qdrant server. It proves whole-directory retention, a concurrent write after the first real snapshot, and post-archive artifact loss all fail their corresponding checks.

Verification: selected P01 checks completed with 9 passing tests, including two real-Qdrant integration guards; Ruff, Ty, and scoped whitespace checks passed. S03, S04, and S05 each received independent review approval. The shared plan state was updated only with `vaultspec-core` and intentionally remains unstaged with existing shared plan work.
