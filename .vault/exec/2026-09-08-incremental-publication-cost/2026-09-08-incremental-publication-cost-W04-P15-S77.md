---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:0ef14ac1bb6e58a5d515b0bad4d54928120ff5035549dcf7bcedb605bca90dea'
step_id: 'S77'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove the finished implementation meets issue 469 with source integration and crash-recovery coverage, deterministic operation-count scaling, a large-parent single-change benchmark, one full repository gate run, and one final code review

## Scope

- `src/vaultspec_rag/tests`

## Changes

- `D` `.vault/exec/2026-09-08-incremental-publication-cost/2026-09-08-incremental-publication-cost-W04-P15-S77.md`
- `M` `docs/cli.md`
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
- `M` `src/vaultspec_rag/indexer/_streaming_types.py`
- `M` `src/vaultspec_rag/indexer/_vault_fingerprint.py`
- `M` `src/vaultspec_rag/mcp/_tools.py`
- `M` `src/vaultspec_rag/search/_validation.py`
- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/serviceclient/_search_transport.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/store_catalog.py`
- `D` `src/vaultspec_rag/tests/benchmarks/bench_incremental_publication_cost.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_kind_restart.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_route_migration.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `M` `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `M` `src/vaultspec_rag/tests/test_config.py`
- `M` `src/vaultspec_rag/tests/test_http_search_errors.py`
- `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `M` `src/vaultspec_rag/tests/test_publication_scaling.py`
- `A` `src/vaultspec_rag/tests/test_scoped_publication_cost_guard.py`
- `M` `src/vaultspec_rag/tests/test_service_search_diagnostics.py`
- `M` `src/vaultspec_rag/tests/test_slice_writer_overlap.py`
- `M` `src/vaultspec_rag/tests/test_source_types.py`
- `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `M` `src/vaultspec_rag/tests/test_vault_fingerprint.py`

- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-all` -> `pass`
- `verify:` `just test-python` -> `pass`

## Notes

The gate run above is the CPU-only lane, not the whole suite. It selects
4,678 of 5,445 collected tests and deselects 767 by marker: the integration,
quality, performance, robustness, subprocess-GPU, CUDA and MPS tiers. Those
767 include the real-Qdrant integration suites this issue's acceptance
criteria depend on for exact breadth, deletion, backend identity and
concurrent publication, and they have not been run here. An earlier version
of this record reported the four exit codes without that distinction, which
read as full-suite coverage.

Before that, the lane was not merely narrow - it was refused outright. A
deleted test took the next one's tier marker with it, and a test declaring
no tier makes the tier gate reject every selection, so each worker exited
before running anything. No gate run on this branch had executed a single
test until that marker was restored.

The large-index performance budget the Step names has not been measured. The
deterministic half is gated and mutation-proven: an exact-path read retires
the same instruction count over a 10-path parent and a 10,000-path one, and
the statement production actually emits is explained and required to seek
every table it touches. The elapsed-time half needs a representative index
and a lane to run it in, and has neither here. The benchmark that stood in
for it was collected by no lane and asserted no threshold, so it is deleted
rather than left as evidence it never provided.

The formal code review ran and returned a fail with three blocking findings,
all of them about evidence rather than design. Each is addressed above and
re-driven in both directions. The Step stays open for the re-review.
