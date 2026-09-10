---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:c714f8bb7ed12c0ec6dc2e64065e27eb97e2c6406976c603feb2dd37a6d9209f'
step_id: 'S39'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Require CLI publication and rebuild requests to carry explicit authority through the reindex transport and validate it without granting scoped scan permission

## Scope

- `src/vaultspec_rag/cli/_index.py`
- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/server/_routes_reindex.py`
- `src/vaultspec_rag/mcp/_tools.py`
- `src/vaultspec_rag/_integrity_remediation.py`
- `src/vaultspec_rag/tests/test_integrity_remediation.py`
- `src/vaultspec_rag/tests`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `A` `.vault/audit/2026-09-09-incremental-publication-cost-s39-cli-authority-audit.md`
- `M` `src/vaultspec_rag/_integrity_remediation.py`
- `M` `src/vaultspec_rag/cli/_index.py`
- `M` `src/vaultspec_rag/mcp/_tools.py`
- `M` `src/vaultspec_rag/server/_routes_reindex.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`
- `M` `src/vaultspec_rag/tests/integration/_service_search_diagnostics_support.py`
- `M` `src/vaultspec_rag/tests/integration/test_document_mcp.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_eviction.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_jobs_routes_controls.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_lifecycle_runtime.py`
- `M` `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`
- `M` `src/vaultspec_rag/tests/test_cli_index.py`
- `M` `src/vaultspec_rag/tests/test_cli_search.py`
- `M` `src/vaultspec_rag/tests/test_integrity_remediation.py`
- `M` `src/vaultspec_rag/tests/test_search_timeout.py`
- `M` `src/vaultspec_rag/tests/test_server_routes.py`
- `verify:` CLI publication/rebuild wire-authority mutation -> `fail`
- `verify:` restored CLI publication/rebuild wire-authority guards -> `pass`
- `verify:` permissive route-authority mutation -> `fail`
- `verify:` restored missing, mismatched, audit, and matching route-authority matrix -> `pass`
- `verify:` removed CLI audit-refusal mutation for both publication paths -> `fail`
- `verify:` restored CLI audit-refusal guards -> `pass`
- `verify:` omitted integrity-remediation authority guard -> `fail`
- `verify:` incorrect integrity-remediation rebuild-authority mutation -> `fail`
- `verify:` restored integrity-remediation publication-authority guard -> `pass`
- `verify:` benchmark legacy source-alias guard -> `fail`
- `verify:` restored benchmark canonical publication payload guard -> `pass`
- `verify:` focused CLI, transport, route, and MCP regression suite (201 tests) -> `pass`
- `verify:` `uv run --frozen pytest -q src/vaultspec_rag/tests/test_integrity_remediation.py` -> `pass`
- `verify:` `uv run --frozen pytest -q -m unit` -> `fail`
- `verify:` `uv run --frozen ruff format --check <all modified Python files>` -> `pass`
- `verify:` `uv run --frozen ruff check <all modified Python files>` -> `pass`
- `verify:` `uv run --frozen ty check src/vaultspec_rag` -> `pass`
- `verify:` `uv run --frozen basedpyright src/vaultspec_rag` -> `pass`
- `verify:` explicit transport, job-starter, and canonical source-value census -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` independent S39 code review -> `pass`

## Notes

The full unit gate reported 4,626 passed, 3 skipped, and 6 failures outside S39: configuration-reference default drift, duplicated finalization phase ownership, pre-existing duplicate function shapes, an undeclared test substitution, binary-workflow drift, and CI runner trust-boundary drift.

The GPU-marked service source-type integration module was refused before collection because no compatible machine-pointer service lease was available. Its wire contract is covered by the CPU route, transport, CLI, and benchmark guards plus repository-wide static analysis.
