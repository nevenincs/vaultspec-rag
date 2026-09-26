---
tags:
  - '#exec'
  - '#gpu-single-owner'
date: '2026-09-26'
modified: '2026-09-26'
body_schema: 'body-v2'
body_hash: 'sha256:8fb07bba40a9c7e180a1c7253a06933309ecb68f2bbd5a630de3ce2899b7b515'
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
- `S04` `M` `src/vaultspec_rag/_service_borrower.py`
- `S04` `M` `src/vaultspec_rag/_service_residency.py`
- `S04` `M` `src/vaultspec_rag/gpu_borrow_lease.py`
- `S04` `M` `src/vaultspec_rag/cli/_service_start.py`
- `S04` `M` `src/vaultspec_rag/tests/conftest.py`
- `S04` `M` `src/vaultspec_rag/tests/test_gpu_owner.py`
- `S04` `M` `src/vaultspec_rag/tests/test_gpu_borrow_lease.py`
- `S04` `M` `src/vaultspec_rag/tests/test_torch_load_centralized.py`
- `S04` `M` `src/vaultspec_rag/tests/test_cli_qdrant.py`
- `S04` `M` `src/vaultspec_rag/tests/test_substitution_discipline.py`
- `S04` `M` `src/vaultspec_rag/tests/test_process_probe_source_structure.py`
- `S04` `verify:` `ruff check` -> `pass`
- `S04` `verify:` `ruff format --check` -> `pass`
- `S04` `verify:` `ty check` -> `pass`
- `S04` `verify:` `basedpyright` -> `pass`
- `S04` `verify:` `pytest -m unit test_gpu_owner test_gpu_borrow_lease test_cli_qdrant test_torch_load_centralized test_process_probe_source_structure test_cli_server_start test_service_quiesce_controller test_job_manager_quiesce test_lifespan_machine_lock` -> `pass`
- `S04` `verify:` `guard mutations (bind without lend, resume without reclaim, start ignoring the owner) fail then pass` -> `pass`
- `S04` `by:` `orchestrator`
- `S07` `M` `src/vaultspec_rag/operator_state/_provisioning.py`
- `S07` `M` `src/vaultspec_rag/commands/_tool_torch.py`
- `S07` `M` `src/vaultspec_rag/cli/_service_doctor.py`
- `S07` `M` `docs/installation.md`
- `S07` `M` `src/vaultspec_rag/tests/test_service_env_preflight.py`
- `S07` `M` `src/vaultspec_rag/tests/test_server_doctor.py`
- `S07` `verify:` `ruff check` -> `pass`
- `S07` `verify:` `ruff format --check` -> `pass`
- `S07` `verify:` `ty check` -> `pass`
- `S07` `verify:` `basedpyright` -> `pass`
- `S07` `verify:` `mdformat --check and pymarkdownlnt scan docs/installation.md` -> `pass`
- `S07` `verify:` `pytest test_service_env_preflight test_tool_torch_repair test_server_doctor test_cli_install` -> `pass`
- `S07` `verify:` `guard mutations (upgrade drops the recorded wheel, pin disclosure removed, doctor advises uv tool upgrade) fail then pass` -> `pass`
- `S07` `by:` `vaultspec-high-executor`
- `S05` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S05` `M` `src/vaultspec_rag/cli/_search.py`
- `S05` `M` `src/vaultspec_rag/tests/test_gpu_owner.py`
- `S05` `M` `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `S05` `M` `src/vaultspec_rag/tests/test_service_version_compatibility.py`
- `S05` `verify:` `ruff check` -> `pass`
- `S05` `verify:` `ruff format --check` -> `pass`
- `S05` `verify:` `ty check` -> `pass`
- `S05` `verify:` `basedpyright` -> `pass`
- `S05` `verify:` `pytest -m unit test_gpu_owner test_cli_search_safety test_cli_search test_search_service_first test_service_version_compatibility test_cli_install test_qdrant_identity test_service_preflight_cli` -> `pass`
- `S05` `verify:` `guard mutations (local search beside an owner, mandate exempting a foreign release, load refusal without next actions) fail then pass` -> `pass`
- `S05` `by:` `orchestrator`
- `S08` `M` `src/vaultspec_rag/commands/_install.py`
- `S08` `M` `src/vaultspec_rag/commands/_models.py`
- `S08` `M` `src/vaultspec_rag/commands/_tool_torch.py`
- `S08` `M` `src/vaultspec_rag/cli/_install.py`
- `S08` `M` `src/vaultspec_rag/cli/_render.py`
- `S08` `M` `src/vaultspec_rag/cli/_gpu_errors.py`
- `S08` `M` `src/vaultspec_rag/tests/test_cli_install.py`
- `S08` `M` `src/vaultspec_rag/tests/test_tool_torch_repair.py`
- `S08` `verify:` `ruff check` -> `pass`
- `S08` `verify:` `ruff format --check` -> `pass`
- `S08` `verify:` `ty check` -> `pass`
- `S08` `verify:` `basedpyright` -> `pass`
- `S08` `verify:` `pytest test_cli_install test_tool_torch_repair test_install_mode test_install_provision test_install_client_role test_install_mcp_extra test_install_torch_config test_service_env_preflight` -> `pass`
- `S08` `verify:` `guard mutations (hard-coded install action, warnings copies restored, refusal rendered as a full report, second post-install probe) fail then pass` -> `pass`
- `S08` `by:` `vaultspec-high-executor`

## Notes

- `S02` `test_substitution_discipline` fails on the base branch for `test_storage_maintenance_tick.py` (substitution added by d18045e8, outside this plan); left untouched
- `S06` `test_process_probe_source_structure::test_no_large_duplicate_function_bodies` fails on an uncommitted `_gpu_owner.py:permits_compute` body from the parallel phase, not on this Step's paths
- `S04` P01.S03 left `test_process_probe_source_structure` failing: `permits_compute` joined the allowed membership-test shape group only here
- `S04` `test_substitution_discipline` still fails only on `test_storage_maintenance_tick.py` from base commit d18045e8, outside this plan
- `S07` uv 0.12.x verified in an isolated `UV_TOOL_DIR` sandbox: an == pin makes uv tool upgrade a no-op and uv names uv tool install pkg@latest; `pkg[extras]@latest` with --force, --python and --with installs and records the extras unpinned
