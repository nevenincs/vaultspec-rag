---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:89dbd24d5243a4169441cbb32579b2b76087809d7f63a90dcdec2fb22a78851f'
step_id: 'S52'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Carry required publication and verification authority through the exact job codec, every production constructor, immutable transition, and attempt context

## Scope

- `src/vaultspec_rag/job_models.py`
- `src/vaultspec_rag/job_manager/models.py`
- `src/vaultspec_rag/job_manager/_control.py`
- `src/vaultspec_rag/job_manager/_execution.py`
- `src/vaultspec_rag/job_manager/_persistence.py`
- `src/vaultspec_rag/job_persistence.py`
- `src/vaultspec_rag/_job_admission.py`
- `src/vaultspec_rag/jobs.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_routes_reindex.py`
- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/watcher_execution.py`
- `src/vaultspec_rag/tests`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `M` `src/vaultspec_rag/_job_admission.py`
- `M` `src/vaultspec_rag/job_manager/_execution.py`
- `M` `src/vaultspec_rag/job_manager/models.py`
- `M` `src/vaultspec_rag/job_models.py`
- `M` `src/vaultspec_rag/job_persistence.py`
- `M` `src/vaultspec_rag/jobs.py`
- `M` `src/vaultspec_rag/server/_routes.py`
- `M` `src/vaultspec_rag/server/_routes_reindex.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/tests/_job_manager_transition_helpers.py`
- `M` `src/vaultspec_rag/tests/benchmarks/bench_progress_publish.py`
- `M` `src/vaultspec_rag/tests/integration/_index_job_control_support.py`
- `M` `src/vaultspec_rag/tests/integration/_service_jobs_route_helpers.py`
- `M` `src/vaultspec_rag/tests/integration/test_content_policy_fail_closed.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_execution.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`
- `M` `src/vaultspec_rag/tests/integration/test_index_job_control_managed.py`
- `M` `src/vaultspec_rag/tests/integration/test_index_reuse_daemon_path.py`
- `M` `src/vaultspec_rag/tests/integration/test_index_support_admission.py`
- `M` `src/vaultspec_rag/tests/integration/test_jobs_registry_quarantine.py`
- `M` `src/vaultspec_rag/tests/integration/test_jobs_registry_recovery.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_job_control.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_job_control_pause_restart.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_job_control_transport_matrix.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_resilience.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_routes_controls.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_lifecycle_runtime.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`
- `M` `src/vaultspec_rag/tests/test_job_contracts.py`
- `M` `src/vaultspec_rag/tests/test_job_contracts_persistence.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_admission.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_degradation.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_encode_admission.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_loopless_dispatch.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_quiesce.py`
- `M` `src/vaultspec_rag/tests/test_job_manager_transitions.py`
- `M` `src/vaultspec_rag/tests/test_job_progress_durability.py`
- `M` `src/vaultspec_rag/tests/test_job_resilience.py`
- `M` `src/vaultspec_rag/tests/test_job_retry_resolution.py`
- `M` `src/vaultspec_rag/tests/test_job_runtime_owner_tickets.py`
- `M` `src/vaultspec_rag/tests/test_jobs_lifecycle.py`
- `M` `src/vaultspec_rag/tests/test_search_availability.py`
- `M` `src/vaultspec_rag/tests/test_service_quiesce_routes.py`
- `M` `src/vaultspec_rag/tests/test_service_registry_quiesce_transitions.py`
- `M` `src/vaultspec_rag/tests/test_service_registry_recovery.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `M` `src/vaultspec_rag/tests/test_watcher_quiesce_intake.py`
- `M` `src/vaultspec_rag/tests/test_watcher_transition_logging.py`
- `M` `src/vaultspec_rag/watcher_execution.py`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_contracts.py -k "explicit_authority or canonical_authority or serializes_one_explicit_authority_shape or active_work_identity"` -> `fail`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_contracts.py -k "explicit_authority or canonical_authority or serializes_one_explicit_authority_shape or active_work_identity"` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_contracts_persistence.py -k "explicit_authority or idempotency_spec_writes or version_one or missing_persisted_authority or old_start_paused"` -> `fail`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_contracts_persistence.py -k "explicit_authority or idempotency_spec_writes or version_one or missing_persisted_authority or old_start_paused"` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_manager_encode_admission.py -k "dispatch_context_carries or dispatch_refuses_authority"` -> `fail`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_manager_encode_admission.py -k "dispatch_context_carries or dispatch_refuses_authority"` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_manager_transitions.py -k "pause_resume_race or terminal_first_writer"` -> `fail`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_manager_transitions.py -k "pause_resume_race or terminal_first_writer"` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py::test_job_mutations_keep_real_asgi_loop_responsive` -> `fail`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py::test_job_mutations_keep_real_asgi_loop_responsive` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_contracts.py src/vaultspec_rag/tests/test_job_contracts_persistence.py src/vaultspec_rag/tests/test_job_manager_admission.py src/vaultspec_rag/tests/test_job_manager_encode_admission.py src/vaultspec_rag/tests/test_job_manager_transitions.py` -> `pass`
- `verify:` `uv run --frozen pytest -q <all modified non-integration test modules>` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_jobs_registry_quarantine.py src/vaultspec_rag/tests/integration/test_jobs_registry_recovery.py src/vaultspec_rag/tests/integration/test_service_job_control.py src/vaultspec_rag/tests/integration/test_service_jobs_resilience.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_service_job_control.py src/vaultspec_rag/tests/integration/test_service_job_control_transport_matrix.py src/vaultspec_rag/tests/integration/test_service_jobs_routes_controls.py src/vaultspec_rag/tests/integration/test_index_support_admission.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_service_jobs_routes_collection.py src/vaultspec_rag/tests/integration/test_service_jobs_routes_auth.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_process_probe_vocabulary_guards.py` -> `pass`
- `verify:` `uv run --no-sync ruff format --check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync ruff check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync ty check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync basedpyright <all modified Python files>` -> `pass`
- `verify:` `repository-wide AST authority constructor and POST /jobs payload census` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md --json` -> `pass`
- `verify:` `vaultspec-core vault check all --json` -> `pass`
- `verify:` `git diff --check` -> `pass`

## Notes

The remaining changed integration modules could not start because another process held the GPU borrower lease. The explicit GPU-discipline gate refused the mixed integration selection before collection; no GPU-dependent test was skipped or run concurrently.
