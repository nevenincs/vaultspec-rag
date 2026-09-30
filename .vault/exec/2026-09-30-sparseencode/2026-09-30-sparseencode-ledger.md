---
tags:
  - '#exec'
  - '#sparseencode'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:f22799c1e2f4e071e51e5438b9dae158d591fe755c62cddc1b97d5df346ef7e3'
related:
  - "[[2026-09-30-sparseencode-plan]]"
---

# `sparseencode` ledger

## Changes

- `S01` `M` `.env.example`
- `S01` `M` `.github/workflows/ci.yml`
- `S01` `M` `.github/workflows/hardware.yml`
- `S01` `M` `.github/workflows/release-please.yml`
- `S01` `M` `.release-please-manifest.json`
- `S01` `M` `CHANGELOG.md`
- `S01` `M` `README.md`
- `S01` `M` `assets/term-doctor.svg`
- `S01` `M` `conftest.py`
- `S01` `M` `dev/gates.py`
- `S01` `M` `dev/guards/test_ci_hardware_tiers.py`
- `S01` `M` `dev/toolchain.py`
- `S01` `M` `docs/configuration.md`
- `S01` `M` `docs/glossary.md`
- `S01` `M` `docs/indexing.md`
- `S01` `M` `docs/installation.md`
- `S01` `M` `pyproject.toml`
- `S01` `M` `src/vaultspec_rag/__init__.py`
- `S01` `M` `src/vaultspec_rag/_operator_commands.py`
- `S01` `M` `src/vaultspec_rag/_readiness.py`
- `S01` `M` `src/vaultspec_rag/_store_models.py`
- `S01` `M` `src/vaultspec_rag/cli/__init__.py`
- `S01` `M` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S01` `M` `src/vaultspec_rag/commands/_install.py`
- `S01` `M` `src/vaultspec_rag/commands/_provision.py`
- `S01` `M` `src/vaultspec_rag/config/_credentials.py`
- `S01` `M` `src/vaultspec_rag/config/_registry.py`
- `S01` `M` `src/vaultspec_rag/config/_settings.py`
- `S01` `M` `src/vaultspec_rag/config/_types.py`
- `S01` `M` `src/vaultspec_rag/embeddings.py`
- `S01` `M` `src/vaultspec_rag/indexer/_slicing.py`
- `S01` `M` `src/vaultspec_rag/search/_searcher.py`
- `S01` `M` `src/vaultspec_rag/store_collections.py`
- `S01` `M` `src/vaultspec_rag/store_runtime.py`
- `S01` `M` `src/vaultspec_rag/store_schema.py`
- `S01` `M` `src/vaultspec_rag/tests/_model_setup.py`
- `S01` `M` `src/vaultspec_rag/tests/_tier_gate.py`
- `S01` `M` `src/vaultspec_rag/tests/conftest.py`
- `S01` `M` `src/vaultspec_rag/tests/integration/test_embeddings.py`
- `S01` `M` `src/vaultspec_rag/tests/quality/evidence_queries.toml`
- `S01` `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `S01` `M` `src/vaultspec_rag/tests/test_cli_warmup.py`
- `S01` `M` `src/vaultspec_rag/tests/test_config_backend.py`
- `S01` `M` `src/vaultspec_rag/tests/test_dev_aggregators.py`
- `S01` `M` `src/vaultspec_rag/tests/test_encode_bucket_planner.py`
- `S01` `M` `src/vaultspec_rag/tests/test_env_credentials.py`
- `S01` `M` `src/vaultspec_rag/tests/test_env_registry.py`
- `S01` `M` `src/vaultspec_rag/tests/test_gpu_session_lock.py`
- `S01` `D` `src/vaultspec_rag/tests/test_hf_gated_repo_error.py`
- `S01` `M` `src/vaultspec_rag/tests/test_hook_sandbox.py`
- `S01` `M` `src/vaultspec_rag/tests/test_install_client_role.py`
- `S01` `M` `src/vaultspec_rag/tests/test_install_torch_config.py`
- `S01` `M` `src/vaultspec_rag/tests/test_model_setup.py`
- `S01` `M` `src/vaultspec_rag/tests/test_provision.py`
- `S01` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S01` `M` `src/vaultspec_rag/tests/test_service_registry.py`
- `S01` `M` `src/vaultspec_rag/tests/test_storage_identity.py`
- `S01` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S01` `M` `uv.lock`
- `S01` `A` `src/vaultspec_rag/_model_cache.py`
- `S01` `A` `src/vaultspec_rag/_sparse_encoder.py`
- `S01` `A` `src/vaultspec_rag/_sparse_profile.py`
- `S01` `A` `.vault/adr/2026-09-30-sparseencode-adr.md`
- `S01` `A` `.vault/plan/2026-09-30-sparseencode-plan.md`
- `S01` `A` `.vault/research/2026-09-30-sparseencode-research.md`
- `S01` `A` `.vault/index/sparseencode.index.md`
- `S01` `verify:` `just check-python` -> `pass`
- `S01` `verify:` `just check-type` -> `pass`
- `S01` `verify:` `just check-type-strict` -> `pass`
- `S01` `verify:` `just check-toml` -> `pass`
- `S01` `verify:` `just check-docs-version` -> `pass`
- `S01` `verify:` `just check-docs-conventions` -> `pass`
- `S01` `verify:` `just check-workflow` -> `pass`
- `S01` `verify:` `pytest focused encoder/model/storage/provision/config/lease/readiness/dev/CI selection (16 files; 295 passed)` -> `pass`
- `S01` `verify:` `pytest integration/test_embeddings pinned sparse parity and bounded output retention (3 passed; borrowed RTX 4080 SUPER)` -> `pass`
- `S01` `verify:` `worker surface selection (174 passed) and stable review follow-up selection (17 passed)` -> `pass`
- `S01` `verify:` `guard mutation proofs (4 encoder, 5 surfaces, 3 development guards; intended fail then restored pass)` -> `pass`
- `S01` `verify:` `just build-python and wheel metadata/module inspection (0.6.0)` -> `pass`
- `S01` `verify:` `expanded retired model/acquisition reference sweep` -> `pass`
- `S01` `by:` `supervisor with GPT-6.1 Sol executors`
- `S01` `A` `.vault/audit/2026-09-30-sparseencode-audit.md`
- `S01` `verify:` `just check-markdown` -> `pass`
- `S01` `verify:` `vault plan check sparseencode` -> `pass`
