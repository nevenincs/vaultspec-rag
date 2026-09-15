---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-14'
body_schema: 'body-v2'
body_hash: 'sha256:d53a6ae79fc9d92ee1bb237f56530cbaecf7d7b0814ca04bc80933c1cc9bc8dc'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---

# `platform-backend-selection` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/_gpu.py`
- `S02` `T` `src/vaultspec_rag/_gpu_admission.py`
- `S03` `T` `src/vaultspec_rag/memory_probe.py`
- `S04` `T` `src/vaultspec_rag/tests/test_torch_load_centralized.py`
- `S05` `T` `src/vaultspec_rag/tests/test_gpu_admission.py`
- `S08` `T` `src/vaultspec_rag/embeddings.py`
- `S09` `T` `src/vaultspec_rag/service.py`
- `S10` `T` `src/vaultspec_rag/search/_searcher.py`
- `S11` `T` `src/vaultspec_rag/indexer/_streaming.py`
- `S12` `T` `src/vaultspec_rag/tests/test_encode_bucket_planner.py`
- `S13` `T` `src/vaultspec_rag/tests/test_service_registry.py`
- `S14` `T` `src/vaultspec_rag/api.py`
- `S15` `T` `src/vaultspec_rag/_readiness.py`
- `S16` `T` `src/vaultspec_rag/server/_state.py`
- `S17` `T` `src/vaultspec_rag/tests/test_readiness.py`
- `S18` `T` `src/vaultspec_rag/tests/test_api_clean_admission.py`
- `S19` `T` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S20` `T` `src/vaultspec_rag/cli/_process.py`
- `S21` `T` `src/vaultspec_rag/cli/_status.py`
- `S22` `T` `src/vaultspec_rag/torch_config/_diagnose.py`
- `S23` `T` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S24` `T` `src/vaultspec_rag/tests/integration/test_mps_backend.py`
- `S25` `T` `pyproject.toml`
- `S26` `T` `.github/workflows/ci.yml`
- `S27` `T` `README.md`
- `S28` `T` `docs/architecture.md`
- `S29` `T` `docs/getting-started.md`
- `S30` `T` `docs/installation.md`
- `S31` `T` `docs/indexing.md`
- `S32` `T` `docs/service-mode.md`
- `S33` `T` `docs/cli.md`
- `S34` `T` `docs/glossary.md`
- `S35` `T` `platform-backend-selection change set`
- `S36` `T` `src/vaultspec_rag/cli/_service_start.py`
- `S37` `T` `src/vaultspec_rag/tests/test_torch_config.py`
- `S38` `T` `justfile`
- `S39` `T` `src/vaultspec_rag/tests/_tier_gate.py`
- `S40` `T` `src/vaultspec_rag/tests/conftest.py`
- `S41` `T` `src/vaultspec_rag/tests/test_marker_discipline.py`
- `S42` `T` `src/vaultspec_rag/cli/_install.py`
- `S43` `T` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S44` `T` `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`
- `S45` `T` `src/vaultspec_rag/tests/test_cli_status.py`
- `S46` `T` `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`
- `S47` `T` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S48` `T` `src/vaultspec_rag/api.py`
- `S48` `T` `src/vaultspec_rag/tests/test_api_clean_admission.py`
- `S49` `T` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S49` `T` `src/vaultspec_rag/cli/_status.py`
- `S49` `T` `src/vaultspec_rag/tests/test_cli_install.py`
- `S49` `T` `src/vaultspec_rag/tests/test_cli_status.py`
- `S50` `T` `src/vaultspec_rag/_gpu_admission.py`
- `S50` `T` `src/vaultspec_rag/tests/test_gpu_admission.py`
- `S51` `T` `src/vaultspec_rag/tests/integration/test_mps_backend.py`
- `S51` `T` `src/vaultspec_rag/tests/test_marker_discipline.py`
- `S52` `T` `.github/workflows/ci.yml`
- `S52` `T` `src/vaultspec_rag/tests/test_marker_discipline.py`
- `S53` `T` `README.md`
- `S53` `T` `docs/getting-started.md`
