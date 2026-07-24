---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S20'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# fix or explicitly file the rebuild-replays-deleted-collections defect: storage delete leaves the resume ledger, so a rebuild replays committed vectors instead of rebuilding

## Scope

- `repro plus fix plus guard test`
- `escalating if the ledger delete contract must change`
- `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `storage delete surface`
- `tests`

## Description

- Reproduce the rebuild replay: interrupt a clean rebuild after its first
  storage-confirmed unit, drop the code collection the way storage delete does
  (collection gone, per-root run ledger intact), rerun the clean rebuild, and
  observe the resumed generation skip its committed units with zero encoding.
- Add `_checkpoint_evidence_lost` in
  `src/vaultspec_rag/indexer/_codebase_indexer.py`: a generation carrying
  commit evidence (`ingestion_complete` or committed units > 0) whose
  collection no longer exists (`VaultStore.code_collection_exists`) is retired
  as INVALIDATED and the checkpoint reopened fresh.
- Guard test
  `test_clean_rebuild_reencodes_when_collection_vanished_under_the_ledger`
  in `src/vaultspec_rag/tests/integration/test_index_job_control.py` binds the
  staleness guard: full store-content assertion plus `resumed_units == 0`.

## Outcome

Rebuilds no longer trust ledger evidence for a destroyed collection; the stale
generation is retired and everything re-encodes. No delete-contract change was
required: the fix validates carried evidence at read time, so the storage
delete verb keeps its collection-only scope.

### Addendum 2026-07-24: same exposure closed on the incremental path

The incremental path carried the identical defect one layer up. Root cause:
`_incremental_index_locked` in
`src/vaultspec_rag/indexer/_codebase_indexer.py` diffs the current scan
against the carried metadata sidecar before any run checkpoint opens, so
after an external collection drop every surviving file hashes as unchanged
and the run short-circuits into a mutation-free "unchanged" success over an
empty collection - the checkpoint-level guard is never even reached.

- Repro first: new guard test
  `test_incremental_reencodes_when_collection_vanished_under_published_metadata`
  (beside the rebuild guard) - full index a real corpus with the embedded
  backend, `drop_code_table()` (the storage-delete equivalent), run an
  incremental index, assert complete store content. Failed as predicted on
  the missing-points assertion: stored path set was empty while the run
  reported success.
- Fix, symmetrical with the rebuild guard: `_published_evidence_lost()` -
  published metadata present and `code_collection_exists()` false - checked
  at the top of `_incremental_index_locked` (covers the scoped dispatch too),
  escalating to a full failure-safe reconciliation instead of trusting the
  carried evidence.
- Guard proof both directions in one sequence: validation mutated out
  (helper short-circuited to `False`) -> test red on the missing-points
  assertion (`assert set(stored) == expected_paths`); restored -> green.
  Rebuild guard re-run green alongside.
- Gates on touched files: ruff check + format, basedpyright, ty
  `--python-platform all`, complexity gate, citation gate - all green; full
  `test_index_job_control.py` suite green.

## Notes

- This record was scaffolded late (S20 was appended to the plan after the
  phase's records were cut); the base sections were reconstructed from the
  landed rebuild fix, and the addendum documents the follow-up session.
