---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:562107a4d107793bc58bb9b47d1c5c8696a853af8c4b7a5cc72e170664348256'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# `server-first-default` ledger

## Changes

- `S01` `T` `src/vaultspec_rag/config.py`
- `S02` `T` `src/vaultspec_rag/config.py`
- `S03` `T` `src/vaultspec_rag/config.py`
- `S04` `T` `src/vaultspec_rag/tests/test_config.py`
- `S05` `T` `src/vaultspec_rag/server/_lifespan.py`
- `S06` `T` `src/vaultspec_rag/server/_lifespan.py`
- `S07` `T` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `S08` `T` `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`
- `S09` `T` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S10` `T` `src/vaultspec_rag/cli/_process.py`
- `S11` `T` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S12` `T` `src/vaultspec_rag/tests/test_cli_server_start.py`
- `S13` `T` `src/vaultspec_rag/commands/_provision.py`
- `S14` `T` `src/vaultspec_rag/commands/_provision.py`
- `S15` `T` `src/vaultspec_rag/commands/_provision.py`
- `S16` `T` `src/vaultspec_rag/commands/_provision.py`
- `S17` `T` `src/vaultspec_rag/commands/__init__.py`
- `S18` `T` `src/vaultspec_rag/commands/_install.py`
- `S18` `T` `src/vaultspec_rag/commands/_models.py`
- `S19` `T` `src/vaultspec_rag/cli/_install.py`
- `S20` `T` `src/vaultspec_rag/cli/_install.py`
- `S21` `T` `src/vaultspec_rag/commands/_install.py`
- `S21` `T` `src/vaultspec_rag/config.py`
- `S22` `T` `src/vaultspec_rag/commands/_models.py`
- `S23` `T` `src/vaultspec_rag/cli/_render.py`
- `S24` `T` `src/vaultspec_rag/tests/test_provision.py`
- `S25` `T` `src/vaultspec_rag/tests/integration/test_install.py`
- `S26` `T` `src/vaultspec_rag/api.py`
- `S27` `T` `src/vaultspec_rag/api.py`
- `S28` `T` `src/vaultspec_rag/api.py`
- `S29` `T` `src/vaultspec_rag/api.py`
- `S30` `T` `src/vaultspec_rag/tests/test_readiness.py`
- `S31` `T` `src/vaultspec_rag/cli/_service_doctor.py`
- `S32` `T` `src/vaultspec_rag/cli/__init__.py`
- `S33` `T` `src/vaultspec_rag/server/_routes.py`
- `S34` `T` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S35` `T` `docs/getting-started.md`
- `S36` `T` `docs/installation.md`
- `S37` `T` `docs/service-mode.md`
- `S38` `T` `.vaultspec/rules/rules/vaultspec-rag.builtin.md`
- `S39` `T` `src/vaultspec_rag/cli/_service_lifecycle.py`
- `S42` `T` `docs/cli.md`
- `S40` `A` `.vault/audit/2026-06-13-server-first-default-audit.md`
- `S41` `verify:` `Historical 1218 unit and 44 feature integration tests recorded in 2026-06-13-server-first-default-W04-P10-summary` -> `pass`

## Notes

- `S40` Historical operation attributed from Git commit 304ff0ee52d1088b3404aaf6a429e2da091e348a. Actual retained persona audit addition and W04-P10 summary establish doctor human/JSON, install/start help, and local-only install dry-run. Actual default/local-only daemon start and setup are not established by those narrower observations.
- `S41` This preserves the reported unit/feature-integration result. No full repository integration run or fresh execution is asserted.
