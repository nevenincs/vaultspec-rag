---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:888a25633cb70d28583a9fc8924e47b8d0f63aaa20f16a5d5b2f108a10056221'
step_id: 'S08'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---

# Prove active-receipt visibility and proof revision races across independent SQLite connections

## Scope

- `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py::test_independent_connection_observes_an_active_publication_receipt` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py::test_independent_connection_observes_an_active_publication_receipt` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py::test_read_token_rejects_a_revision_committed_by_an_independent_writer` -> `fail`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py::test_read_token_rejects_a_revision_committed_by_an_independent_writer` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe check src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe format --check src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py` -> `pass`
- `verify:` `.venv/Scripts/ty.exe check src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py` -> `pass`
- `verify:` `.venv/Scripts/basedpyright.exe src/vaultspec_rag/tests/test_index_run_ledger_concurrency.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `vaultspec-core vault check all` -> `pass`
