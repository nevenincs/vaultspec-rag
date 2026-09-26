---
tags:
  - '#exec'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:5ef44e1bb8ae968d468ab97bbf387b4197afc3b19e1681a86a892f6e04026ba6'
related:
  - "[[2026-09-26-gpu-single-owner-plan]]"
---

# `gpu-single-owner` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/_process_probe.py`
- `S01` `A` `src/vaultspec_rag/tests/test_process_lineage.py`
- `S01` `verify:` `ruff check` -> `pass`
- `S01` `verify:` `ruff format --check` -> `pass`
- `S01` `verify:` `ty check` -> `pass`
- `S01` `verify:` `basedpyright` -> `pass`
- `S01` `verify:` `pytest test_process_lineage.py test_process_probe_os_guards.py test_process_probe_source_structure.py` -> `pass`
- `S01` `by:` `orchestrator`
- `S02` `M` `src/vaultspec_rag/_anchor_claim.py`
- `S02` `M` `src/vaultspec_rag/_gpu_admission.py`
- `S02` `M` `src/vaultspec_rag/_win32.py`
- `S02` `A` `src/vaultspec_rag/tests/test_hardware_anchor.py`
- `S02` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S02` `verify:` `ruff check` -> `pass`
- `S02` `verify:` `ruff format --check` -> `pass`
- `S02` `verify:` `ty check` -> `pass`
- `S02` `verify:` `basedpyright` -> `pass`
- `S02` `verify:` `pytest -m unit test_hardware_anchor gpu_admission test_existing_anchor_observation test_gpu_borrow_lease test_gpu_borrow_captured_target` -> `pass`
- `S02` `verify:` `guard mutations (env-read anchor dir, temp-dir load window, no read-only fallback) fail then pass` -> `pass`
- `S02` `by:` `orchestrator`
- `S06` `A` `src/vaultspec_rag/operator_state/_topology.py`
- `S06` `A` `src/vaultspec_rag/operator_state/_provisioning.py`
- `S06` `M` `src/vaultspec_rag/commands/_tool_torch.py`
- `S06` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S06` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S06` `M` `src/vaultspec_rag/cli/_render.py`
- `S06` `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S06` `M` `src/vaultspec_rag/tests/test_tool_torch_repair.py`
- `S06` `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `S06` `verify:` `ruff check` -> `pass`
- `S06` `verify:` `ruff format --check` -> `pass`
- `S06` `verify:` `ty check` -> `pass`
- `S06` `verify:` `basedpyright` -> `pass`
- `S06` `verify:` `pytest test_service_env_preflight test_tool_torch_repair test_cli_install test_cli_status test_environment_probe test_cli_server_start test_cli_start_outcomes test_install_mode test_install_provision test_install_client_role test_server_doctor test_readiness_holders` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S03` `A` `src/vaultspec_rag/_gpu_owner.py`
- `S03` `M` `src/vaultspec_rag/_gpu.py`
- `S03` `M` `src/vaultspec_rag/_machine_lock.py`
- `S03` `M` `src/vaultspec_rag/_operator_commands.py`
- `S03` `A` `src/vaultspec_rag/tests/test_gpu_owner.py`
- `S03` `M` `src/vaultspec_rag/tests/test_torch_load_centralized.py`
- `S03` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S03` `verify:` `ruff check` -> `pass`
- `S03` `verify:` `ruff format --check` -> `pass`
- `S03` `verify:` `ty check` -> `pass`
- `S03` `verify:` `basedpyright` -> `pass`
- `S03` `verify:` `pytest -m unit test_gpu_owner test_torch_load_centralized test_lifespan_machine_lock test_machine_discovery gpu_admission` -> `pass`
- `S03` `verify:` `guard mutations (stranger admitted, loan start time ignored, service lock ignored, unopenable anchor read free, load_accelerator unchecked) fail then pass` -> `pass`
- `S03` `by:` `orchestrator`

## Notes

- `S02` `test_substitution_discipline` fails on the base branch for `test_storage_maintenance_tick.py` (substitution added by d18045e8, outside this plan); left untouched
- `S06` `test_process_probe_source_structure::test_no_large_duplicate_function_bodies` fails on an uncommitted `_gpu_owner.py:permits_compute` body from the parallel phase, not on this Step's paths
