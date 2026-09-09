---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:2977a11d5883c681379b987ba3672ab032fe6eb7fbfc63afff5ab3d845c0eff3'
step_id: 'S38'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Enforce authority-specific execution admission for generic service jobs without widening scoped publication

## Scope

- `src/vaultspec_rag/job_dispatch.py`
- `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `src/vaultspec_rag/tests/integration/test_document_execution.py`
- `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `A` `.vault/audit/2026-09-09-incremental-publication-cost-s38-execution-admission-audit.md`
- `M` `src/vaultspec_rag/job_dispatch.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_execution.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_resource_bounds.py`
- `verify:` permissive dispatch-authority guard mutation -> `fail`
- `verify:` restored dispatch-authority guard matrix -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/integration/test_service_jobs_routes_mutations.py` -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_job_manager_encode_admission.py` -> `pass`
- `verify:` `uv run --no-sync ruff format --check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync ruff check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync ty check <all modified Python files>` -> `pass`
- `verify:` `uv run --no-sync basedpyright <all modified Python files>` -> `pass`
- `verify:` `_AttemptDispatch` constructor and removed `clean`-field census -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md --json` -> `pass`
- `verify:` independent S38 code review -> `pass`

## Notes

The two unchanged document integration regression nodes were refused before collection because another process held the GPU borrower lease. Their S38-only edits supply required constructor arguments; focused execution guards and strict static gates passed.
