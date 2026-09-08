---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:4e802f8228ada1d81f6cb08e3c1657ad92334ef90bff0d499d0392f8ddf398cc'
step_id: 'S11'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Emit controller-only readiness notifications after canonical desired-state persistence without advancing publication

## Scope

- `src/vaultspec_rag/job_manager/_control.py`
- `src/vaultspec_rag/job_manager/manager.py`
- `src/vaultspec_rag/job_manager/state.py`
- `src/vaultspec_rag/service.py`
- `and src/vaultspec_rag/server/_search_readiness.py`

## Changes

- `M` `src/vaultspec_rag/job_manager/_control.py`
- `M` `src/vaultspec_rag/job_manager/manager.py`
- `M` `src/vaultspec_rag/job_manager/state.py`
- `M` `src/vaultspec_rag/service.py`
- `M` `src/vaultspec_rag/server/_search_readiness.py`
- `M` `.vault/plan/2026-09-08-search-readiness-contract-plan.md`
- `M` `.vault/index/search-readiness-contract.index.md`
- `A` `.vault/exec/2026-09-08-search-readiness-contract/2026-09-08-search-readiness-contract-W01-P03-S11.md`
- `verify:` `uv run ruff format --check src/vaultspec_rag/job_manager/_control.py src/vaultspec_rag/job_manager/manager.py src/vaultspec_rag/job_manager/state.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/job_manager/_control.py src/vaultspec_rag/job_manager/manager.py src/vaultspec_rag/job_manager/state.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/job_manager/_control.py src/vaultspec_rag/job_manager/manager.py src/vaultspec_rag/job_manager/state.py src/vaultspec_rag/service.py src/vaultspec_rag/server/_search_readiness.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_job_manager_transitions.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_job_contracts_persistence.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_service_registry_recovery.py` -> `pass`
