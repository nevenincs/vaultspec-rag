---
tags:
  - '#plan'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:ca1f7893f70898b73a8888f2a11f210ff5b3d8826c85484046843acaedb81712'
tier: L2
related:
  - '[[2026-07-27-lint-defaults-adr]]'
  - '[[2026-07-27-lint-defaults-research]]'
  - '[[2026-07-27-lint-defaults-ruff-complexity-reference]]'
---

# `lint-defaults` plan

Restore Ruff's upstream complexity defaults through one file-scoped remediation
step for every current finding, followed by an explicit gate restoration and full
inventory verification.

### Phase `P01` - Core and search contracts

Refactor core modules and search behavior so internal operations meet upstream complexity defaults without changing observable results.

- [x] `P01.S01` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_atomic_write.py`.
- [x] `P01.S02` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_domain.py`.
- [x] `P01.S03` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_loopback_http.py`.
- [x] `P01.S04` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_operator_commands.py`.
- [x] `P01.S05` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_process_probe.py`.
- [x] `P01.S06` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_public_search.py`.
- [x] `P01.S07` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_store_search.py`.
- [x] `P01.S08` - Remediate upstream-default complexity findings; `src/vaultspec_rag/_store_writes.py`.
- [x] `P01.S09` - Remediate upstream-default complexity findings; `src/vaultspec_rag/api.py`.
- [x] `P01.S27` - Remediate upstream-default complexity findings; `src/vaultspec_rag/generation_survey.py`.
- [x] `P01.S28` - Remediate upstream-default complexity findings; `src/vaultspec_rag/index_profiles.py`.
- [x] `P01.S61` - Remediate upstream-default complexity findings; `src/vaultspec_rag/search/_postprocess.py`.
- [x] `P01.S62` - Remediate upstream-default complexity findings; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P01.S63` - Remediate upstream-default complexity findings; `src/vaultspec_rag/search/_validation.py`.

### Phase `P02` - CLI, command, and MCP boundaries

Classify public transport signatures, refactor internal helpers, and retain only approved boundary exceptions.

- [x] `P02.S10` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_app.py`.
- [x] `P02.S11` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_index.py`.
- [x] `P02.S12` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_install.py`.
- [x] `P02.S13` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_process.py`.
- [x] `P02.S14` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_search.py`.
- [x] `P02.S15` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_jobs.py`.
- [x] `P02.S16` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P02.S17` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_logs.py`.
- [x] `P02.S18` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P02.S19` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P02.S20` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_service_watcher.py`.
- [x] `P02.S21` - Remediate upstream-default complexity findings; `src/vaultspec_rag/cli/_status_render.py`.
- [x] `P02.S22` - Remediate upstream-default complexity findings; `src/vaultspec_rag/commands/_install.py`.
- [x] `P02.S23` - Remediate upstream-default complexity findings; `src/vaultspec_rag/commands/_provision.py`.
- [x] `P02.S24` - Remediate upstream-default complexity findings; `src/vaultspec_rag/commands/_torch_flow.py`.
- [x] `P02.S25` - Remediate upstream-default complexity findings; `src/vaultspec_rag/commands/_uninstall.py`.
- [x] `P02.S55` - Remediate upstream-default complexity findings; `src/vaultspec_rag/mcp/_admin_client.py`.
- [x] `P02.S56` - Remediate upstream-default complexity findings; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `P03` - Indexer pipeline

Decompose indexing and preprocessing operations while preserving checkpoint, lifecycle, and GPU ownership behavior.

- [x] `P03.S29` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_ast_chunker.py`.
- [x] `P03.S30` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_chunk_producer.py`.
- [x] `P03.S31` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P03.S32` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_code_meta.py`.
- [x] `P03.S33` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P03.S34` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_config_epoch.py`.
- [x] `P03.S35` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_consumer_pipeline.py`.
- [x] `P03.S36` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_content_discovery.py`.
- [x] `P03.S37` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_document_checkpoint.py`.
- [x] `P03.S38` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_document_indexer.py`.
- [x] `P03.S39` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_document_meta.py`.
- [x] `P03.S40` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_donor_candidates.py`.
- [x] `P03.S41` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [x] `P03.S42` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_incremental_commit.py`.
- [x] `P03.S43` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_index_lifecycle.py`.
- [x] `P03.S44` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `P03.S45` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_resolved_policy.py`.
- [x] `P03.S46` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_reuse.py`.
- [x] `P03.S47` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_route_migration.py`.
- [x] `P03.S48` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_run_checkpoint.py`.
- [x] `P03.S49` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P03.S50` - Remediate upstream-default complexity findings; `src/vaultspec_rag/indexer/_vault_indexer.py`.

### Phase `P04` - Service, runtime, and watcher behavior

Reduce complexity in service, runtime, job, and watcher paths with behavior-preserving extractions.

- [x] `P04.S26` - Remediate upstream-default complexity findings; `src/vaultspec_rag/embeddings.py`.
- [x] `P04.S51` - Remediate upstream-default complexity findings; `src/vaultspec_rag/job_dispatch.py`.
- [x] `P04.S52` - Remediate upstream-default complexity findings; `src/vaultspec_rag/job_manager.py`.
- [x] `P04.S53` - Remediate upstream-default complexity findings; `src/vaultspec_rag/jobs.py`.
- [x] `P04.S54` - Remediate upstream-default complexity findings; `src/vaultspec_rag/logging_config.py`.
- [x] `P04.S57` - Remediate upstream-default complexity findings; `src/vaultspec_rag/memory_probe.py`.
- [x] `P04.S58` - Remediate upstream-default complexity findings; `src/vaultspec_rag/qdrant_runtime/_provision.py`.
- [x] `P04.S59` - Remediate upstream-default complexity findings; `src/vaultspec_rag/qdrant_runtime/_resolve.py`.
- [x] `P04.S60` - Remediate upstream-default complexity findings; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.
- [x] `P04.S64` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_main.py`.
- [x] `P04.S65` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_routes_jobs.py`.
- [x] `P04.S66` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `P04.S67` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_routes_storage.py`.
- [x] `P04.S68` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_routes.py`.
- [x] `P04.S69` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_search_availability.py`.
- [x] `P04.S70` - Remediate upstream-default complexity findings; `src/vaultspec_rag/server/_watcher.py`.
- [x] `P04.S71` - Remediate upstream-default complexity findings; `src/vaultspec_rag/serviceclient/_discovery.py`.
- [x] `P04.S72` - Remediate upstream-default complexity findings; `src/vaultspec_rag/serviceclient/_status.py`.
- [x] `P04.S73` - Remediate upstream-default complexity findings; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `P04.S74` - Remediate upstream-default complexity findings; `src/vaultspec_rag/storage_ops.py`.
- [x] `P04.S75` - Remediate upstream-default complexity findings; `src/vaultspec_rag/store_schema.py`.
- [x] `P04.S76` - Remediate upstream-default complexity findings; `src/vaultspec_rag/store.py`.
- [x] `P04.S93` - Remediate upstream-default complexity findings; `src/vaultspec_rag/watcher_retry.py`.
- [x] `P04.S94` - Remediate upstream-default complexity findings; `src/vaultspec_rag/watcher.py`.

### Phase `P05` - Real-behavior test fixtures

Restructure test setup and integration scenarios without replacing production behavior with fakes or duplicated logic.

- [x] `P05.S77` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/_cli_helpers.py`.
- [x] `P05.S78` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/_model_setup.py`.
- [x] `P05.S79` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`.
- [x] `P05.S80` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/conftest.py`.
- [x] `P05.S81` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_codebase_integration.py`.
- [x] `P05.S82` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`.
- [x] `P05.S83` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.
- [x] `P05.S84` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [x] `P05.S85` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.
- [x] `P05.S86` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.
- [x] `P05.S87` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [x] `P05.S88` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/test_cli_watcher.py`.
- [x] `P05.S89` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/test_config_epoch.py`.
- [x] `P05.S90` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`.
- [x] `P05.S91` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/test_preprocess_batch.py`.
- [x] `P05.S92` - Remediate upstream-default complexity findings; `src/vaultspec_rag/tests/test_service_registry.py`.

### Phase `P06` - Default gate and closeout

Restore configured defaults and prove the full upstream-threshold inventory is empty.

- [x] `P06.S95` - Restore Ruff upstream complexity defaults and preserve dedicated preview coverage; `pyproject.toml`.

## Description

This plan executes the accepted default-restoration decision. The first five
phases classify each signature from callers, structurally reduce internal
complexity, and preserve real behavior tests. The final phase lowers the configured
limits only after the source inventory is empty.

## Steps

Evidence gap: the retained document body has no authored Steps content beyond scaffold comments or placeholders.

## Parallelization

P01, P02, P03, and P04 may proceed in parallel by file where no caller or
shared request value crosses the boundary. P05 follows the corresponding
production changes. P06 is last because the lower limits must not be enabled
until all structural remediation is complete.

## Verification

Each changed cluster runs its focused real-behavior tests, Ruff, formatting, and
type checks. Completion requires all 95 Steps closed, the configured
upstream-default complexity gate for PLR0911, PLR0913, PLR0915, and preview
PLR1702 clean, and an isolated run of that same gate reporting zero findings.
