---
tags:
  - '#exec'
  - '#qdrant-provisioning-trust'
date: '2026-10-05'
modified: '2026-10-05'
body_schema: 'body-v2'
body_hash: 'sha256:920b41ac481ff094b353244777ea7747752d64a72187687e30d493a63d955151'
related:
  - "[[2026-10-05-qdrant-provisioning-trust-plan]]"
---

# `qdrant-provisioning-trust` ledger

## Changes

- `S06` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S06` `M` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S06` `M` `src/vaultspec_rag/cli/_service_qdrant.py`
- `S06` `M` `src/vaultspec_rag/commands/_install.py`
- `S06` `M` `src/vaultspec_rag/commands/_provision.py`
- `S06` `M` `src/vaultspec_rag/tests/test_cli_progress_surfaces.py`
- `S06` `M` `src/vaultspec_rag/tests/test_cli_qdrant.py`
- `S06` `M` `src/vaultspec_rag/tests/test_install_client_role.py`
- `S06` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S06` `A` `src/vaultspec_rag/tests/_qdrant_provision_seam.py`
- `S06` `A` `src/vaultspec_rag/tests/test_client_provisions_nothing.py`
- `S06` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S06` `verify:` `pytest unit lane over 15 covering modules` -> `pass`
- `S06` `verify:` `dev lint python` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S09` `M` `.env.example`
- `S09` `M` `docs/configuration.md`
- `S09` `M` `src/vaultspec_rag/config/_registry.py`
- `S09` `M` `src/vaultspec_rag/config/_schema.py`
- `S09` `M` `src/vaultspec_rag/config/_settings.py`
- `S09` `M` `src/vaultspec_rag/config/_types.py`
- `S09` `M` `src/vaultspec_rag/tests/test_config_backend.py`
- `S09` `A` `src/vaultspec_rag/tests/test_config_sources.py`
- `S09` `verify:` `pytest over HEAD plus the seventeen joint-commit files` -> `pass`
- `S09` `verify:` `ruff, ty, basedpyright on the committed paths` -> `pass`
- `S09` `by:` `vaultspec-high-executor`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S01` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S01` `M` `tools/qdrant_pin_digests.py`
- `S01` `verify:` `pytest test_qdrant_runtime.py test_process_probe_vocabulary_guards.py` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S14` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S14` `M` `src/vaultspec_rag/qdrant_runtime/_resolve.py`
- `S14` `M` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `S14` `M` `src/vaultspec_rag/tests/test_process_probe_vocabulary_guards.py`
- `S14` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S14` `verify:` `pytest test_qdrant_runtime.py test_process_probe_vocabulary_guards.py test_readiness.py` -> `pass`
- `S14` `by:` `vaultspec-high-executor`
- `S02` `M` `conftest.py`
- `S02` `M` `src/vaultspec_rag/_readiness.py`
- `S02` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S02` `M` `src/vaultspec_rag/qdrant_runtime/_resolve.py`
- `S02` `M` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/_helpers.py`
- `S02` `M` `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`
- `S02` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S02` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S02` `verify:` `pytest on 7 covering files` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S08` `M` `conftest.py`
- `S08` `M` `src/vaultspec_rag/qdrant_runtime/_constants.py`
- `S08` `M` `src/vaultspec_rag/qdrant_runtime/_resolve.py`
- `S08` `M` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `S08` `M` `src/vaultspec_rag/tests/_fake_qdrant_binary.py`
- `S08` `M` `src/vaultspec_rag/tests/integration/_helpers.py`
- `S08` `M` `src/vaultspec_rag/tests/integration/test_qdrant_long_paths.py`
- `S08` `M` `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`
- `S08` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_credential.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_load_concurrency.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_runtime.py`
- `S08` `A` `src/vaultspec_rag/tests/test_qdrant_spawn_trust.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_store_format.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_store_resilience.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_supervise.py`
- `S08` `M` `src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py`
- `S08` `verify:` `pytest on 12 covering files excluding two superseded TestProvision cases` -> `pass`
- `S08` `by:` `vaultspec-high-executor`
- `S07` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S07` `A` `src/vaultspec_rag/tests/test_start_provisioning.py`
- `S07` `M` `docs/cli.md`
- `S07` `M` `src/vaultspec_rag/cli/_service_qdrant.py`
- `S07` `M` `src/vaultspec_rag/tests/test_cli_qdrant.py`
- `S07` `verify:` `pytest unit lane in an exported tree` -> `pass`
- `S07` `by:` `vaultspec-high-executor`
- `S12` `M` `src/vaultspec_rag/cli/_install.py`
- `S12` `A` `src/vaultspec_rag/cli/_provision_progress.py`
- `S12` `M` `src/vaultspec_rag/cli/_render.py`
- `S12` `M` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S12` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S12` `M` `src/vaultspec_rag/commands/_install.py`
- `S12` `A` `src/vaultspec_rag/commands/_model_fetch.py`
- `S12` `M` `src/vaultspec_rag/commands/_provision.py`
- `S12` `A` `src/vaultspec_rag/tests/_model_cache_seed.py`
- `S12` `M` `src/vaultspec_rag/tests/test_cli_progress_surfaces.py`
- `S12` `M` `src/vaultspec_rag/tests/test_client_provisions_nothing.py`
- `S12` `A` `src/vaultspec_rag/tests/test_model_fetch.py`
- `S12` `M` `src/vaultspec_rag/tests/test_start_provisioning.py`
- `S12` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S12` `verify:` `pytest unit lane over 22 covering modules` -> `pass`
- `S12` `verify:` `dev lint python, complexity, size, nesting, docs-cli` -> `pass`
- `S12` `by:` `vaultspec-high-executor`

## Notes

- `S06` Commits bed82805 and 5c754e91. The 5c754e91 message states 28 tests in `test_provision.py;` the true count is 24. GPU and integration tiers not run: resident service stopped.
- `S09` Commit e605fc13, shared with the S10 downloader half and the S07 reader half because the declared-but-unread settings guards forbid landing settings without their readers. Tree-wide lint type is red on `tests/test_monitor_inventory.py,` which predates this plan.
- `S01` Commit a2a61208. All six archive digests reproduced from the pinned host; executable digests derived three ways with identical results. No binary executed.
- `S14` Commit c414417b.
- `S02` Commit 71727554. A set-but-unusable operator setting raises rather than falling through to the managed install.
- `S08` Commit aeda6411. Two TestProvision cases were red only against the then-uncommitted install-state change and were removed in ab883647. Integration supervisor call sites type-check but were not executed: resident service stopped.
- `S07` Commits e605fc13 (joint, reader half) and 544f095a (status label). The start-time console announcement of an operator-supplied binary landed with S12 in 3676b615, where the start's binary decision moved into the provisioning front door.
- `S12` Commit 3676b615. server warmup now exits 1 when a model could not be fetched or is missing offline. The download-success branch of the model fetch had no unit coverage at this commit.
