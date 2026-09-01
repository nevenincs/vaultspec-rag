---
tags:
  - '#plan'
  - '#generation-accounting'
date: '2026-09-01'
tier: L1
related:
  - '[[2026-09-01-generation-accounting-adr]]'
  - '[[2026-09-01-generation-accounting-repair-research]]'
  - '[[2026-09-01-generation-accounting-repair-reference]]'
modified: '2026-09-01'
body_hash: 'sha256:2d8a76628f42a7ac793105a95ee60fb9432c4d473bbefe4346df45de7235dfa2'
---

# `generation-accounting` plan

Repair build-target ownership, resumed outcome convergence, and runtime reindex timeout resolution.

## Description

Repair the accepted generation-accounting decision through its existing lifecycle, drift,
ledger, and service-client owners. Clean-generation mutations stay on the
lifecycle-derived build collection until publication; resumed retained outcomes retire
storage before ledger state; and reindex resolves its configured timeout for each request.

## Steps

- [x] `S01` - Thread the lifecycle-derived active build target through clean-generation cleanup without rebinding the served collection before publication; `src/vaultspec_rag/indexer`.
- [x] `S02` - Add canonical retirement for resumed retained outcomes with storage confirmation before ledger mutation; `src/vaultspec_rag/indexer/_drift_owner.py`.
- [x] `S03` - Resolve the reindex timeout at the production HTTP call boundary; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `S04` - Prove clean-generation cleanup mutates only the active build collection; `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.
- [x] `S05` - Prove resumed skip and vanished outcomes retire retained storage before finalization; `src/vaultspec_rag/tests/test_run_checkpoint.py`.
- [x] `S06` - Prove a live reindex timeout override reaches the HTTP request; `src/vaultspec_rag/tests/test_search_timeout.py`.
- [x] `S07` - Retire retained empty-source outcomes through the canonical storage-confirmed path; `src/vaultspec_rag/indexer/_consumer_pipeline.py`.
- [x] `S08` - Prove retained empty-source outcomes finalize after storage retirement; `src/vaultspec_rag/tests/test_run_checkpoint.py`.
- [x] `S09` - Preserve the explicit collection through code write and deletion table preparation; `src/vaultspec_rag/store_ingest.py`.
- [x] `S10` - Prove target-scoped code deletion never initializes the served collection; `src/vaultspec_rag/tests/test_store_codebase.py`.
- [x] `S11` - Constrain clean-generation reconciliation to the active build collection before publication; `src/vaultspec_rag/indexer/_route_migration.py`.
- [x] `S12` - Prove clean-generation publication never reconciles the served collection early; `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.
- [x] `S13` - Probe a resumed clean generation's explicit build collection when validating retained storage evidence; `src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [x] `S14` - Prove a missing in-progress clean build is retired instead of publishing a partial replacement; `src/vaultspec_rag/tests/integration/test_index_rebuild_survivability.py`.
- [x] `S15` - Retain the deleted root identity through prefix-addressed server-storage deletion for resident-service eviction; `src/vaultspec_rag/storage_survey_ops.py`.
- [x] `S16` - Prove prefix-addressed deletion retains the attributed root required for resident-service eviction; `src/vaultspec_rag/tests/integration/test_storage_delete_addressing.py`.

## Parallelization

The transport implementation and its request-boundary test can proceed independently.
Generation ownership, resumed retirement implementation, and their real-storage and ledger
tests form one ordered lane: establish explicit target propagation, implement retirement
through the drift owner, then add regression coverage.

## Verification

Run the new focused tests first, including the guard-failure demonstration and restored
pass. Run strict type checking, formatting, the relevant unit tests, the touched integration
tests under the repository's GPU discipline, the complete non-GPU test tier, and final code
review before completion.
