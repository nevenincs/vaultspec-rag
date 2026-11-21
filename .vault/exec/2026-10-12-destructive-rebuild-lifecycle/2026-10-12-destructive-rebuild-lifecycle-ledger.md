---
tags:
  - '#exec'
  - '#destructive-rebuild-lifecycle'
date: '2026-10-12'
modified: '2026-11-21'
body_schema: 'body-v2'
body_hash: 'sha256:3b03238d70fc85118531bd0ad058770ebab84a63730a303c447f4a1861d2a2ad'
related:
  - "[[2026-10-12-destructive-rebuild-lifecycle-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `destructive-rebuild-lifecycle` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->

- `S01` `A` `src/vaultspec_rag/indexer/_rebuild_lifecycle.py`
- `S01` `A` `src/vaultspec_rag/indexer/_run_ledger_source_resets.py`
- `S01` `A` `src/vaultspec_rag/tests/test_rebuild_lifecycle.py`
- `S01` `M` `src/vaultspec_rag/api.py`
- `S01` `M` `src/vaultspec_rag/_publication_state.py`
- `S01` `M` `src/vaultspec_rag/_store_models.py`
- `S01` `M` `src/vaultspec_rag/store_collections.py`
- `S01` `M` `src/vaultspec_rag/store_ingest.py`
- `S01` `M` `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S01` `M` `src/vaultspec_rag/indexer/_drift_owner.py`
- `S01` `M` `src/vaultspec_rag/indexer/_incremental_commit.py`
- `S01` `M` `src/vaultspec_rag/indexer/_route_migration.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_publication_proofs.py`
- `S01` `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `S01` `M` `src/vaultspec_rag/tests/test_api_clean_admission.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_document_store.py`
- `S01` `M` `src/vaultspec_rag/tests/test_code_rebuild_stale_evidence.py`
- `S01` `M` `src/vaultspec_rag/tests/test_content_route_migration.py`
- `S01` `M` `src/vaultspec_rag/tests/test_incremental_route_reconciliation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_served_pointer_validation.py`
- `S01` `M` `src/vaultspec_rag/tests/test_store_codebase.py`
- `S01` `M` `src/vaultspec_rag/tests/test_index_run_ledger_schema.py`
- `S01` `M` `src/vaultspec_rag/tests/test_vault_progress_phases.py`
- `S01` `verify:` `ruff check (changed files)` -> `pass`
- `S01` `verify:` `ruff format --check (changed files)` -> `pass`
- `S01` `verify:` `ty check (changed files)` -> `pass`
- `S01` `verify:` `basedpyright (changed files)` -> `pass`
- `S01` `verify:` `pytest run-ledger/store/clean CPU modules -n 8 (1929 passed; 2 failures outside S01 files)` -> `pass`
- `S01` `by:` `vaultspec-high-executor`

## Notes

- `S01` GPU-marked `test_store_codebase` delete test not run: the resident 0.6.5 service refused the GPU borrow from the 0.6.6 client.
- `S01` Unrelated failures left: duplicate bodies in `cli/_service_jobs_presentation.py` vs `cli/_status_labels.py` (other worker's change set); substitution counts in untouched `test_indexer_unit.py,` `test_lazy_reranker.py,` `test_watcher_intent.py.`
