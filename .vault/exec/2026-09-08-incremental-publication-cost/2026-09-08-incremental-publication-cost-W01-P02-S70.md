---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:64c15f7acd435cb9d600a35e32795019ac5b82df7c3fcafa703bd079fe66b0ff'
step_id: 'S70'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Require backend identity in run signatures and checkpoint requests, delete legacy defaults and decoder fallbacks, and update every constructor

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `src/vaultspec_rag/tests/test_checkpoint_common.py`
- `src/vaultspec_rag/tests/test_config_epoch.py`
- `src/vaultspec_rag/tests/test_document_index_escalation.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `src/vaultspec_rag/tests/test_run_checkpoint.py`
- `src/vaultspec_rag/tests/test_document_checkpoint.py`
- `src/vaultspec_rag/tests/integration/test_document_watcher.py`
- `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`
- `src/vaultspec_rag/tests/integration/test_content_route_migration.py`
- `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`

## Changes

- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `M` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `M` `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `M` `src/vaultspec_rag/tests/test_checkpoint_common.py`
- `M` `src/vaultspec_rag/tests/test_config_epoch.py`
- `M` `src/vaultspec_rag/tests/test_document_index_escalation.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `M` `src/vaultspec_rag/tests/test_run_checkpoint.py`
- `M` `src/vaultspec_rag/tests/test_document_checkpoint.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_watcher.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_route_migration.py`
- `M` `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_run_signature_and_decoder_require_backend_identity src/vaultspec_rag/tests/test_run_checkpoint.py::test_code_run_open_request_requires_backend_identity src/vaultspec_rag/tests/test_document_checkpoint.py::test_document_run_open_request_requires_backend_identity` -> `fail`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_index_run_ledger.py::test_run_signature_and_decoder_require_backend_identity src/vaultspec_rag/tests/test_run_checkpoint.py::test_code_run_open_request_requires_backend_identity src/vaultspec_rag/tests/test_document_checkpoint.py::test_document_run_open_request_requires_backend_identity` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/test_checkpoint_common.py src/vaultspec_rag/tests/test_config_epoch.py src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py` -> `pass`
- `verify:` `uv run --no-sync pytest -q -n0 src/vaultspec_rag/tests/integration/test_document_watcher.py::test_deleted_path_uses_prior_ledger_owner_not_current_route src/vaultspec_rag/tests/integration/test_document_watcher.py::test_deleted_path_keeps_prior_owner_across_an_incomplete_clean src/vaultspec_rag/tests/integration/test_content_kind_restart.py::test_each_kind_replays_only_its_final_unconfirmed_unit src/vaultspec_rag/tests/integration/test_content_route_migration.py::test_interrupted_destination_first_flip_resumes_idempotently src/vaultspec_rag/tests/integration/test_content_route_migration.py::test_generation_route_cleanup_uses_bounded_store_and_ledger_pages src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py::TestCleanGenerationCleanupKeepsServing::test_stale_cleanup_deletes_from_the_build_collection_only` -> `fail`
- `verify:` `uv run --no-sync ruff format --check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_checkpoint.py src/vaultspec_rag/indexer/_document_checkpoint.py src/vaultspec_rag/tests/test_checkpoint_common.py src/vaultspec_rag/tests/test_config_epoch.py src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py src/vaultspec_rag/tests/integration/test_document_watcher.py src/vaultspec_rag/tests/integration/test_content_kind_restart.py src/vaultspec_rag/tests/integration/test_content_route_migration.py src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_checkpoint.py src/vaultspec_rag/indexer/_document_checkpoint.py src/vaultspec_rag/tests/test_checkpoint_common.py src/vaultspec_rag/tests/test_config_epoch.py src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py src/vaultspec_rag/tests/integration/test_document_watcher.py src/vaultspec_rag/tests/integration/test_content_kind_restart.py src/vaultspec_rag/tests/integration/test_content_route_migration.py src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_checkpoint.py src/vaultspec_rag/indexer/_document_checkpoint.py src/vaultspec_rag/tests/test_checkpoint_common.py src/vaultspec_rag/tests/test_config_epoch.py src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py src/vaultspec_rag/tests/integration/test_document_watcher.py src/vaultspec_rag/tests/integration/test_content_kind_restart.py src/vaultspec_rag/tests/integration/test_content_route_migration.py src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py` -> `pass`
- `verify:` `uv run --no-sync basedpyright src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_checkpoint.py src/vaultspec_rag/indexer/_document_checkpoint.py src/vaultspec_rag/tests/test_checkpoint_common.py src/vaultspec_rag/tests/test_config_epoch.py src/vaultspec_rag/tests/test_document_index_escalation.py src/vaultspec_rag/tests/test_index_run_ledger.py src/vaultspec_rag/tests/test_run_checkpoint.py src/vaultspec_rag/tests/test_document_checkpoint.py src/vaultspec_rag/tests/integration/test_document_watcher.py src/vaultspec_rag/tests/integration/test_content_kind_restart.py src/vaultspec_rag/tests/integration/test_content_route_migration.py src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py` -> `pass`
- `verify:` `$matches = rg -n -F 'legacy:unknown' src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/indexer/_run_ledger_runtime.py src/vaultspec_rag/indexer/_run_checkpoint.py src/vaultspec_rag/indexer/_document_checkpoint.py; if ($LASTEXITCODE -eq 0) { $matches; exit 1 }; exit 0` -> `pass`
- `verify:` `uv run --no-sync vaultspec-core vault check all` -> `pass`
- `verify:` `uv run --no-sync vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The focused integration selection collected no tests because pytest could not capture a version-compatible resident machine-pointer service. The already-running service reports ready, but its installed package is not compatible with this checkout; the guarded GPU tier correctly refused to borrow it.
