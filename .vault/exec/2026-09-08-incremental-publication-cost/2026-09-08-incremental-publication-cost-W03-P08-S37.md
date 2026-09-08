---
tags:
  - '#exec'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:3fb2a6f2b3e6460c603d30f9b7aaf49d89ee99ea83b1248811dae949fd1c374c'
step_id: 'S37'
related:
  - "[[2026-09-08-incremental-publication-cost-plan]]"
---
# Encode persisted publication, rebuild, and audit-verification authority independently of run mode without migration authority

## Scope

- `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `src/vaultspec_rag/tests/test_index_run_ledger.py`

## Changes

- `M` `.vault/plan/2026-09-08-incremental-publication-cost-plan.md`
- `A` `.vault/audit/2026-09-08-incremental-publication-cost-s37-authority-audit.md`
- `M` `src/vaultspec_rag/indexer/_run_ledger_models.py`
- `M` `src/vaultspec_rag/tests/test_index_run_ledger.py`
- `verify:` forbidden migration-authority mutation -> `fail`
- `verify:` closed authority vocabulary restored -> `pass`
- `verify:` `.venv/Scripts/python.exe -m pytest -q src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ruff.exe format --check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/ty.exe check src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `.venv/Scripts/basedpyright.exe src/vaultspec_rag/indexer/_run_ledger_models.py src/vaultspec_rag/tests/test_index_run_ledger.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `vaultspec-core vault plan check .vault/plan/2026-09-08-incremental-publication-cost-plan.md` -> `pass`
- `verify:` `vaultspec-core vault check all` -> `pass`
- `verify:` independent S37 code review -> `pass`
