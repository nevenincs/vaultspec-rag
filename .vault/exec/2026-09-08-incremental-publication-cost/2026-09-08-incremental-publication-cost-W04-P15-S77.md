---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:6e5bd7a80880e2ab177db92690c53f7e9a5914179b41bb1f7cbbdc8e22186351'
step_id: 'S77'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove the finished implementation meets issue 469 with source integration and crash-recovery coverage, deterministic operation-count scaling, a large-parent single-change benchmark, one full repository gate run, and one final code review

## Scope

- `src/vaultspec_rag/tests`
- `src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`

## Changes

- `M` `src/vaultspec_rag/_index_breadth.py`
- `M` `src/vaultspec_rag/_index_integrity.py`
- `M` `src/vaultspec_rag/_operator_commands.py`
- `M` `src/vaultspec_rag/_search_state.py`
- `M` `src/vaultspec_rag/_source_types.py`
- `M` `src/vaultspec_rag/api.py`
- `M` `src/vaultspec_rag/cli/_index.py`
- `M` `src/vaultspec_rag/cli/_search.py`
- `M` `src/vaultspec_rag/indexer/_checkpoint_common.py`
- `M` `src/vaultspec_rag/indexer/_document_checkpoint.py`
- `M` `src/vaultspec_rag/indexer/_document_indexer.py`
- `M` `src/vaultspec_rag/indexer/_generation_lifecycle.py`
- `M` `src/vaultspec_rag/indexer/_publication_proof.py`
- `M` `src/vaultspec_rag/indexer/_run_checkpoint.py`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/indexer/_streaming.py`
- `M` `src/vaultspec_rag/indexer/_vault_fingerprint.py`
- `M` `src/vaultspec_rag/mcp/_tools.py`
- `M` `src/vaultspec_rag/search/_validation.py`
- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/serviceclient/_search_transport.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_route_migration.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `M` `src/vaultspec_rag/tests/test_config.py`
- `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `M` `src/vaultspec_rag/tests/test_slice_writer_overlap.py`
- `M` `src/vaultspec_rag/tests/test_source_types.py`
- `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `M` `docs/cli.md`

- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-all` -> `pass`
- `verify:` `just test-python` -> `pass`

## Notes

The formal code review this Step requires has not run: this session had no
way to dispatch the reviewer persona. Everything else the Step names is
done, and the Step stays open until that review lands.

The tier gate refused every selection until a missing marker was restored,
so no earlier gate run on this branch had executed a single test. The
suites were red, not passing, for as long as the branch existed.
