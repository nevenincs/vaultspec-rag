---
tags:
  - '#exec'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:2f6f0827258978f178f8442753bb61b2060824f30340fa7a424b0a54aa3d262d'
related:
  - "[[2026-07-27-maintainability-remediation-plan]]"
---

# `maintainability-remediation` ledger

## Changes

- `S01` `T`
- `S02` `T`
- `S03` `T`
- `S04` `T` `src/vaultspec_rag/job_manager.py`
- `S05` `T` `src/vaultspec_rag/cli/_service_jobs.py`
- `S06` `T` `src/vaultspec_rag/indexer/_run_ledger.py`
- `S07` `T` `src/vaultspec_rag/tests/integration/test_index_job_control.py`
- `S08` `T`
- `S09` `T` `src/vaultspec_rag/tests/integration/test_jobs_registry.py`
- `S10` `T` `src/vaultspec_rag/tests/integration/_service_job_control_e2e_support.py`
- `S10` `T` `src/vaultspec_rag/tests/integration/test_service_job_control_pause_restart.py`
- `S10` `T` `src/vaultspec_rag/tests/integration/test_service_job_control_transport_matrix.py`
- `S10` `T` `src/vaultspec_rag/tests/integration/test_service_job_control_watcher.py`
- `S11` `T` `src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `S12` `T` `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`
- `S13` `T` `src/vaultspec_rag/tests/integration/_service_search_diagnostics_support.py`
- `S13` `T` `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`
- `S13` `T` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`
- `S13` `T` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `S13` `T` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `S14` `T`
- `S15` `T` `tools/health_report.py`
- `S16` `M` `src/vaultspec_rag/cli/_app.py`
- `S17` `M` `src/vaultspec_rag/indexer/_preprocess_glue.py`
- `S18` `M` `src/vaultspec_rag/tests/test_no_reexports.py`
- `S19` `A` `src/vaultspec_rag/tests/test_mixin_declarations.py`
- `S20` `M` `pyproject.toml`
- `S21` `M` `src/vaultspec_rag/tests/_jobs_tui_harness.py`

## Notes

- `S16` Historical attribution: 8a6c992c3918724327c8af01f73c408a1064cf71 refactor(cli): delete the `server_app` alias, and guard the mixin/dataclass trap. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S17` Historical attribution: 000a324ab70f4d2ad84eeed962b934d35f6cc521 refactor: every module exports only what it defines. Historical change attribution only, not complete Step acceptance or original gates PASS. Historical removal of a zero-caller rename supported; does not certify complete semantic sweep.
- `S18` Historical attribution: 000a324ab70f4d2ad84eeed962b934d35f6cc521 refactor: every module exports only what it defines. Historical change attribution only, not complete Step acceptance or original gates PASS. Guard change supported; original red/green execution not inferred from commit statement.
- `S19` Historical attribution: 8a6c992c3918724327c8af01f73c408a1064cf71 refactor(cli): delete the `server_app` alias, and guard the mixin/dataclass trap. Historical change attribution only, not complete Step acceptance or original gates PASS. Actual guard concerns frozen dataclass mixins. Commit explicitly leaves orphaned decorators to existing type checker; not proof of a dedicated orphan-decorator guard. Actual guard concerns frozen dataclass mixins. Commit explicitly leaves orphaned decorators to existing type checker; not proof of a dedicated orphan-decorator guard.
- `S20` Historical attribution: 1edec8e0d68139439ad7ab44540c5f72ddd99a72 refactor(tests): bring every test module under 1500, and gate them at it. Historical change attribution only, not complete Step acceptance or original gates PASS. Removed test exclusion and module splits recorded in same commit; no full execution acceptance inferred.
- `S21` Historical attribution: 90a9e0ad58f00846acc5a99da3793937030de07d fix(tests): let each watch suite declare its own tier, and clear the strict gate. Historical change attribution only, not complete Step acceptance or original gates PASS. Cross-module harness surface explicitly declared; symbols retained leading underscores. No distributed-stability PASS inferred.
