---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-10-12'
modified: '2026-10-30'
body_schema: 'body-v2'
body_hash: 'sha256:8adfb1d74e6da272d0ef205d13d5fdb08cdfe681e55393ac980e0aa94d082db2'
related:
  - "[[2026-10-12-service-graph-plan]]"
---

# `service-graph` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/graph_cache.py`
- `S01` `M` `src/vaultspec_rag/search/_searcher.py`
- `S01` `M` `src/vaultspec_rag/search/_rerank.py`
- `S01` `M` `src/vaultspec_rag/service.py`
- `S01` `M` `src/vaultspec_rag/_service_eviction.py`
- `S01` `M` `src/vaultspec_rag/tests/test_graph_cache.py`
- `S01` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_performance.py`
- `S01` `verify:` `covering pytest 107 tests and final graph shutdown integration 21 tests` -> `pass`
- `S01` `verify:` `package ruff, changed format, ty, basedpyright` -> `pass`
- `S01` `verify:` `blocking and epoch guard mutations fail and restored pass` -> `pass`
- `S01` `verify:` `installed cold vault 2.98s graph 0.00094s warm 0.59s code 1.87s` -> `pass`
- `S02` `M` `vaultspec-core/src/vaultspec_core/core/corpus_io.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/core/tests/test_corpus_security.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/graph/api.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/graph/cache.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/graph/cache_io.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/graph/tests/test_cache.py`
- `S02` `M` `vaultspec-core/src/vaultspec_core/vaultcore/scanner.py`
- `S02` `verify:` `236 covering tests and 64 cache tests after owner extraction` -> `pass`
- `S02` `verify:` `package ruff, changed format, ty, basedpyright, production pylint` -> `pass`
- `S02` `verify:` `three guard mutations fail and restored guards pass` -> `pass`
- `S02` `verify:` `real graph load 3.17s, single-entry refresh 6.01s, assembly 0.73s, PageRank 0.44s, centrality 0.21s` -> `pass`
- `S02` `verify:` `installed vault query cold 2.11s warm 1.49s code 2.82s` -> `pass`
- `S02` `verify:` `canonical core commit 5cab80da installed source SHA256 and 89 dependency compatibility checks` -> `pass`
- `S03` `M` `vaultspec-core/src/vaultspec_core/config/config.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/config/read_scope.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/config/tests/test_config.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/core/corpus_io.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/core/windows_paths.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/core/tests/test_corpus_security.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/graph/api.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/graph/algorithms.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/graph/tests/test_graph.py`
- `S03` `M` `vaultspec-core/src/vaultspec_core/graph/tests/test_pagerank.py`
- `S03` `M` `vaultspec-core/dev/experiments/graph_profile.py`
- `S03` `verify:` `523 covering tests; four default deselections` -> `pass`
- `S03` `verify:` `Ruff format ty basedpyright Pylint and core commit gates` -> `pass`
- `S03` `verify:` `five guard mutations fail and restored pass` -> `pass`
- `S03` `verify:` `py-spy and controlled resource measurement recorded in core audit` -> `pass`
- `S03` `verify:` `core 618cdf1c installed hashes and 89 dependencies; live vault 3.289s and 0.587s` -> `pass`
- `S04` `M` `.vault/audit/2026-04-02-service-graph-code-review-audit.md`
- `S04` `M` `.vault/audit/2026-10-01-incremental-index-recovery-audit.md`
- `S04` `M` `.vault/plan/2026-10-12-service-graph-plan.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/managed-qdrant-part-03.md`
- `S04` `M` `src/vaultspec_rag/_publication_state.py`
- `S04` `M` `src/vaultspec_rag/commands/_install.py`
- `S04` `M` `src/vaultspec_rag/commands/_uninstall.py`
- `S04` `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `S04` `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `S04` `M` `src/vaultspec_rag/indexer/_vault_incremental.py`
- `S04` `M` `src/vaultspec_rag/indexer/_vault_indexer.py`
- `S04` `M` `src/vaultspec_rag/job_dispatch.py`
- `S04` `M` `src/vaultspec_rag/tests/conftest.py`
- `S04` `M` `src/vaultspec_rag/tests/integration/test_jobs_registry_quarantine.py`
- `S04` `M` `src/vaultspec_rag/tests/test_graph_cache.py`
- `S04` `M` `src/vaultspec_rag/tests/test_incremental_failure_classification.py`
- `S04` `M` `src/vaultspec_rag/tests/test_install_mode.py`
- `S04` `M` `src/vaultspec_rag/tests/test_monitor_browser_render.py`
- `S04` `M` `src/vaultspec_rag/tests/test_publication_read_paths.py`
- `S04` `M` `src/vaultspec_rag/tests/test_search_readiness.py`
- `S04` `M` `src/vaultspec_rag/tests/test_search_readiness_restore.py`
- `S04` `M` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S04` `M` `src/vaultspec_rag/tests/test_vault_checkpoint_exposure.py`
- `S04` `M` `src/vaultspec_rag/tests/test_vault_chunking_unit.py`
- `S04` `M` `src/vaultspec_rag/tests/test_vault_progress_phases.py`
- `S04` `M` `src/vaultspec_rag/tests/test_workspace_link_boundary.py`
- `S04` `A` `src/vaultspec_rag/_context_scope.py`
- `S04` `A` `src/vaultspec_rag/tests/_mcp_consent.py`
- `S04` `verify:` `install and workspace tests with core 0.3.5: 103 passed` -> `pass`
- `S04` `verify:` `recovery integration: 92 passed` -> `pass`
- `S04` `verify:` `graph and rerank: 29 passed` -> `pass`
- `S04` `verify:` `test substitution discipline: 2 passed` -> `pass`
- `S04` `verify:` `server doctor: 13 passed` -> `pass`
- `S04` `verify:` `nine intentional guard mutations fail and restored guards pass` -> `pass`
- `S04` `verify:` `package Ruff and changed-file format and types` -> `pass`
- `S04` `M` `.vault/exec/2026-10-12-service-graph/2026-10-12-service-graph-ledger.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/ci-release-delivery-part-02.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/ci-release-delivery-part-05.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/content-admission-policy-part-03.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/developer-toolchain-part-04.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/gpu-model-runtime-part-01.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/installation-provisioning-part-08.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/mcp-integration-part-01.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/search-retrieval-part-05.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/service-lifecycle-part-18.md`
- `S04` `M` `.vaultspec/skills/start-vaultspec-rag/references/test-infrastructure-part-01.md`
- `S04` `M` `src/vaultspec_rag/tests/_model_fetch_child.py`
- `S04` `M` `src/vaultspec_rag/tests/test_model_fetch.py`
- `S04` `verify:` `full CPU suite: 8145 passed, 16 skips, 5 model failures, 4 missing monitor errors` -> `fail`
- `S04` `verify:` `model modules: 34 passed and last explicit child case corrected and passed` -> `pass`
- `S04` `verify:` `model timeout boundaries: 5 passed` -> `pass`
- `S04` `verify:` `compiled monitor lifecycle: 4 passed` -> `pass`
- `S04` `verify:` `browser rendering: 11 passed` -> `pass`
- `S04` `verify:` `frontend lint format types build` -> `pass`
- `S04` `verify:` `package gates with failed Markdown and links corrected and rerun` -> `pass`
- `S04` `verify:` `core PR 606 Linux Windows lint CodeQL merge gate and merge` -> `pass`
- `S04` `M` `src/vaultspec_rag/indexer/_run_ledger_commits.py`
- `S04` `M` `src/vaultspec_rag/indexer/_run_ledger_runtime.py`
- `S04` `M` `src/vaultspec_rag/tests/test_index_run_ledger_publication_receipts.py`
- `S04` `A` `src/vaultspec_rag/indexer/_run_ledger_recovery.py`
- `S04` `verify:` `corrected package complexipy Ruff and Pylint each exit 0` -> `pass`
- `S04` `verify:` `recovery owner extraction 145 covering tests` -> `pass`
- `S04` `verify:` `confirmation guard mutation fails then three restored states pass` -> `pass`
- `S04` `verify:` `recovery changed-file format ty basedpyright each exit 0` -> `pass`
- `S04` `verify:` `RAG Merge Gate 38303455264 attempt 2, runtime 7e3ccf33: Linux 3.13 8100 passed, Linux 3.14 8099 passed, Windows 8158 passed, package lint and dependency audit` -> `pass`
- `S04` `verify:` `Dev Server 38303455322 and CodeQL on recovery head 7e3ccf33` -> `pass`

## Notes

- `S04` Full Python suite, browser rendering, package gates and PR CI verification remain in progress; S04 stays open.
- `S04` All local failures resolved in focused reruns. Full PR matrix still required; S04 remains open.
- `S04` Corrects prior missed aggregate complexity failures. Required remote matrix remains pending; requested release follows verified PR merge.
- `S04` Original Windows inventory HTTP timeout retained in attempt 1; complete Windows rerun passed without code or guard changes. All required S04 runtime verification now passes; release preparation remains pending.
