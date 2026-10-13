---
tags:
  - '#exec'
  - '#service-runtime'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:33c99587cc83c0f74da63755460e16fc12f586ce08ef1752432b5d04207768a8'
related:
  - "[[2026-10-13-service-runtime-plan]]"
---

# `service-runtime` ledger

## Changes

- `S01` `A` `.vault/audit/2026-10-13-service-runtime-audit.md`
- `S01` `A` `.vault/adr/2026-10-13-service-runtime-adr.md`
- `S01` `M` `.vault/adr/2026-07-14-tool-env-gpu-continuity-adr.md`
- `S01` `M` `.vault/adr/2026-10-05-qdrant-provisioning-trust-adr.md`
- `S01` `A` `.vault/plan/2026-10-13-service-runtime-plan.md`
- `S01` `verify:` `vaultspec-core vault check all` -> `pass`
- `S04` `M` `src/vaultspec_rag/_readiness.py`
- `S04` `M` `src/vaultspec_rag/cli/_service_doctor.py`
- `S04` `M` `src/vaultspec_rag/cli/_status.py`
- `S04` `M` `src/vaultspec_rag/tests/integration/test_service_doctor_liveness.py`
- `S04` `M` `src/vaultspec_rag/tests/test_cli_status.py`
- `S04` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S04` `M` `src/vaultspec_rag/tests/test_readiness_service_environment.py`
- `S04` `M` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S04` `M` `src/vaultspec_rag/tests/test_service_version_compatibility.py`
- `S04` `verify:` `pytest doctor/readiness/status suites` -> `pass`
- `S04` `by:` `vaultspec-standard-executor`
- `S02` `M` `.env.example`
- `S02` `M` `src/vaultspec_rag/cli/_process.py`
- `S02` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S02` `M` `src/vaultspec_rag/config/_registry.py`
- `S02` `M` `src/vaultspec_rag/config/_types.py`
- `S02` `M` `src/vaultspec_rag/operator_state/_service_environment.py`
- `S02` `A` `src/vaultspec_rag/service_runtime.py`
- `S02` `M` `src/vaultspec_rag/tests/test_client_provisions_nothing.py`
- `S02` `M` `src/vaultspec_rag/tests/test_provisioning_gate.py`
- `S02` `M` `src/vaultspec_rag/tests/test_python_child_spawn_sites.py`
- `S02` `A` `src/vaultspec_rag/tests/test_service_runtime.py`
- `S02` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S02` `verify:` `pytest-test_service_runtime-and-runtime-build-integration` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S03` `M` `src/vaultspec_rag/_gpu.py`
- `S03` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S03` `M` `src/vaultspec_rag/cli/_render.py`
- `S03` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S03` `M` `src/vaultspec_rag/commands/_provision.py`
- `S03` `M` `src/vaultspec_rag/commands/_torch_flow.py`
- `S03` `M` `src/vaultspec_rag/operator_state/_compute.py`
- `S03` `M` `src/vaultspec_rag/operator_state/_installation.py`
- `S03` `M` `src/vaultspec_rag/operator_state/_provisioning.py`
- `S03` `M` `src/vaultspec_rag/tests/conftest.py`
- `S03` `M` `src/vaultspec_rag/tests/test_client_provisions_nothing.py`
- `S03` `M` `src/vaultspec_rag/tests/test_install_client_role.py`
- `S03` `M` `src/vaultspec_rag/tests/test_install_provision.py`
- `S03` `M` `src/vaultspec_rag/tests/test_install_torch_config.py`
- `S03` `A` `src/vaultspec_rag/tests/test_one_cause_one_command.py`
- `S03` `M` `src/vaultspec_rag/tests/test_provisioning_gate.py`
- `S03` `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S03` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S03` `verify:` `pytest-one-cause-one-command-and-install-suites` -> `pass`
- `S03` `by:` `vaultspec-high-executor`
- `S03` `M` `src/vaultspec_rag/tests/test_cli.py`
- `S03` `M` `docs/cli.md`
- `S03` `verify:` `merged unit lane, 7872 pass; failures only the vite-less monitor tests` -> `pass`
