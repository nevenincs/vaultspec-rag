---
tags:
  - '#exec'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:5c2d2e004ab052ded2345c9707958e19d61fc420582bace6bd8cf193c9eba88d'
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
- `S15` `M` `src/vaultspec_rag/_readiness.py`
- `S15` `M` `src/vaultspec_rag/api.py`
- `S15` `M` `src/vaultspec_rag/cli/_service_doctor.py`
- `S15` `M` `src/vaultspec_rag/tests/test_readiness.py`
- `S15` `M` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S15` `verify:` `ruff, ruff format, ty` -> `pass`
- `S11` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S11` `M` `src/vaultspec_rag/service.py`
- `S11` `M` `src/vaultspec_rag/_service_types.py`
- `S11` `M` `src/vaultspec_rag/cli/_status_labels.py`
- `S11` `M` `src/vaultspec_rag/cli/_status_render.py`
- `S11` `M` `src/vaultspec_rag/cli/_jobs_tui_status.py`
- `S11` `M` `src/vaultspec_rag/tests/test_cli_service_status.py`
- `S11` `M` `src/vaultspec_rag/tests/test_conformance_surfacing.py`
- `S11` `M` `src/vaultspec_rag/tests/test_health_degraded_clears.py`
- `S11` `M` `src/vaultspec_rag/tests/test_qdrant_store_format.py`
- `S11` `M` `src/vaultspec_rag/tests/_cli_helpers.py`
- `S11` `M` `src/vaultspec_rag/tests/test_jobs_tui_status.py`
- `S11` `M` `src/vaultspec_rag/tests/test_cli_start_outcomes.py`
- `S11` `M` `src/vaultspec_rag/tests/test_service_lifecycle_helpers.py`
- `S11` `M` `src/vaultspec_rag/tests/test_server.py`
- `S11` `verify:` `ruff, ruff format, ty` -> `pass`
- `S10` `M` `src/vaultspec_rag/operator_state/_compute.py`
- `S10` `verify:` `probe timeout guard under mutation` -> `fail`
- `S05` `M` `src/vaultspec_rag/search/_typesafe_transport.py`
- `S05` `M` `src/vaultspec_rag/server/_lifespan.py`
- `S05` `M` `src/vaultspec_rag/cli/_status_labels.py`
- `S05` `M` `src/vaultspec_rag/tests/test_typesafe_status.py`
- `S05` `M` `src/vaultspec_rag/tests/test_typesafe_transport.py`
- `S05` `verify:` `ruff, ruff format, ty` -> `pass`
- `S12` `M` `src/vaultspec_rag/indexer/_preprocess_config.py`
- `S12` `M` `src/vaultspec_rag/indexer/_content_discovery.py`
- `S12` `M` `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `S12` `M` `src/vaultspec_rag/server/_routes_reindex.py`
- `S12` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S12` `M` `src/vaultspec_rag/cli/_preprocess.py`
- `S12` `M` `src/vaultspec_rag/operator_state/_features.py`
- `S12` `A` `src/vaultspec_rag/tests/test_preprocess_hook_state.py`
- `S12` `verify:` `ruff, ruff format, ty` -> `pass`

## Notes

- `S02` DegradationReason adds JOBS_DEGRADED beyond the ADR's list because the service already emits an 'indexing jobs are degraded' reason; broker exit codes moved into operator_state._service as their single home
- `S03` Envelopes owned by other subsystems (quiesce, qdrant runtime, jobs rollup, device load, capabilities, support profile, index, projects, watcher) travel as owner mappings inside the forbid-extra top-level models
- `S09` Server start preflight repointed in this Step because deleting the prose probe left it no other path; its messaging rework remains in S15. Structural duplicate guard gained an enum-label-table allowance and the new named-subset member
- `S10` Role and compute classification moved into operator_state._compute; the child probe script now imports it, so probing an interpreter carrying an older release answers UNKNOWN (never blocking). Admission's no_cuda/torch_absent reasons became ComputeCapability NO_DEVICE/TORCH_MISSING wire values and the NO_DEVICE label broadened to cover CPU builds seen by admission. The post-install warning moved onto the child probe here, ahead of S15, because TorchDiagnosis removal left it no in-process classifier worth keeping
- `S15` Start preflight and post-install warning already consume the probe verdict (S09, S10); this Step moves the doctor's torch axis onto the daemon-interpreter probe. Reading the service-reported verdict when a service answers lands with the typed service-state model in P03/P04
- `S11` DegradationReason keeps JOBS_STALLED (plural, matching the reported count) and adds JOBS_DEGRADED, differing from the ADR's JOB_STALLED listing; /health drops the model-device cuda flag and its verbose Compute row until installation compute renders in P05; the start envelope keeps its own degraded_reasons key
- `S10` P02 phase-review corrections (commit bae3163c): client readiness, in-process error classification of the loaded torch, enum-owned message headlines, cpu-prefixed tags, explicit None default, required remediation, timeout coverage; both new guards pass once restored
- `S05` enrollment_status returns TypesafeReport; the derivable enrolled flag is gone from the wire; labels come from TypesafeState
- `S12` Reading the running service's preprocess mode moved to S16 (plan row corrected) because the service only publishes its mode with the typed feature section; preprocess status JSON gains a hooks state value; the effect line now renders from PreprocessHookState

