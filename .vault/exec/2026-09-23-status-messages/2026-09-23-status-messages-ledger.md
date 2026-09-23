---
tags:
  - '#exec'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:63f8547760345607d6cd1652139fbed5f43313a3b1380a0a5baddc133d0bdc3d'
related:
  - "[[2026-09-23-status-messages-plan]]"
---

# `status-messages` ledger

## Changes

- `S01` `A` `src/vaultspec_rag/operator_state/__init__.py`
- `S01` `A` `src/vaultspec_rag/operator_state/_installation.py`
- `S01` `A` `src/vaultspec_rag/tests/test_operator_state.py`
- `S01` `verify:` `ruff check, ruff format --check, ty check` -> `pass`
- `S02` `A` `src/vaultspec_rag/operator_state/_service.py`
- `S02` `A` `src/vaultspec_rag/operator_state/_features.py`
- `S02` `M` `src/vaultspec_rag/operator_state/_installation.py`
- `S02` `M` `src/vaultspec_rag/_operator_commands.py`
- `S02` `M` `src/vaultspec_rag/serviceclient/_status.py`
- `S02` `M` `src/vaultspec_rag/cli/_status_render.py`
- `S02` `M` `src/vaultspec_rag/tests/test_operator_state.py`
- `S02` `verify:` `ruff, ruff format, ty on touched files` -> `pass`
- `S03` `A` `src/vaultspec_rag/operator_state/_models.py`
- `S03` `A` `src/vaultspec_rag/tests/test_operator_state_models.py`
- `S03` `M` `src/vaultspec_rag/tests/test_operator_state.py`
- `S03` `verify:` `ruff, ruff format, ty` -> `pass`
- `S09` `A` `src/vaultspec_rag/operator_state/_environment_probe.py`
- `S09` `M` `src/vaultspec_rag/operator_state/_installation.py`
- `S09` `M` `src/vaultspec_rag/cli/_process.py`
- `S09` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S09` `M` `src/vaultspec_rag/commands/_tool_torch.py`
- `S09` `A` `src/vaultspec_rag/tests/test_environment_probe.py`
- `S09` `M` `src/vaultspec_rag/tests/test_tool_torch_repair.py`
- `S09` `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S09` `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `S09` `verify:` `ruff, ruff format, ty` -> `pass`
- `S04` `A` `src/vaultspec_rag/operator_state/_hardware.py`
- `S04` `A` `src/vaultspec_rag/tests/test_hardware_probe.py`
- `S04` `M` `src/vaultspec_rag/tests/test_operator_state.py`
- `S04` `verify:` `ruff, ruff format, ty` -> `pass`
- `S10` `A` `src/vaultspec_rag/operator_state/_compute.py`
- `S10` `M` `src/vaultspec_rag/operator_state/_environment_probe.py`
- `S10` `M` `src/vaultspec_rag/operator_state/_installation.py`
- `S10` `M` `src/vaultspec_rag/_readiness.py`
- `S10` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S10` `M` `src/vaultspec_rag/_gpu_admission.py`
- `S10` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S10` `M` `src/vaultspec_rag/commands/_tool_torch.py`
- `S10` `M` `src/vaultspec_rag/torch_config/_constants.py`
- `S10` `D` `src/vaultspec_rag/torch_config/_diagnose.py`
- `S10` `M` `src/vaultspec_rag/torch_config/__init__.py`
- `S10` `M` `src/vaultspec_rag/tests/test_environment_probe.py`
- `S10` `M` `src/vaultspec_rag/tests/test_tool_torch_repair.py`
- `S10` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S10` `M` `src/vaultspec_rag/tests/test_cli_install.py`
- `S10` `M` `src/vaultspec_rag/tests/test_torch_config.py`
- `S10` `M` `src/vaultspec_rag/tests/gpu_admission/test_floor_and_window.py`
- `S10` `M` `src/vaultspec_rag/tests/gpu_admission/test_latch_and_wire.py`
- `S10` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S10` `verify:` `ruff, ruff format, ty` -> `pass`

## Notes

- `S02` DegradationReason adds JOBS_DEGRADED beyond the ADR's list because the service already emits an 'indexing jobs are degraded' reason; broker exit codes moved into operator_state._service as their single home
- `S03` Envelopes owned by other subsystems (quiesce, qdrant runtime, jobs rollup, device load, capabilities, support profile, index, projects, watcher) travel as owner mappings inside the forbid-extra top-level models
- `S09` Server start preflight repointed in this Step because deleting the prose probe left it no other path; its messaging rework remains in S15. Structural duplicate guard gained an enum-label-table allowance and the new named-subset member
- `S10` Role and compute classification moved into operator_state._compute; the child probe script now imports it, so probing an interpreter carrying an older release answers UNKNOWN (never blocking). Admission's no_cuda/torch_absent reasons became ComputeCapability NO_DEVICE/TORCH_MISSING wire values and the NO_DEVICE label broadened to cover CPU builds seen by admission. The post-install warning moved onto the child probe here, ahead of S15, because TorchDiagnosis removal left it no in-process classifier worth keeping

