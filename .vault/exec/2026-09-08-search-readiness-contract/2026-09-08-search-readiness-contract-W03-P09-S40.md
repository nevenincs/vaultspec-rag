---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:0b149f0bb5c2e1dedfa4777f8e617bc785086910a0de62cfd668572b66c10ac5'
step_id: 'S40'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove fallback and timeout safety never recreate adapter readiness diagnosis

## Scope

- `src/vaultspec_rag/tests/test_cli_search_safety.py`

## Changes

- `M` `src/vaultspec_rag/cli/_render.py`
- `M` `src/vaultspec_rag/tests/_cli_helpers.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `M` `src/vaultspec_rag/tests/test_cli_search.py`
- `M` `src/vaultspec_rag/tests/test_cli_search_safety.py`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/cli/_render.py src/vaultspec_rag/tests/_cli_helpers.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/cli/_render.py src/vaultspec_rag/tests/_cli_helpers.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/cli/_render.py src/vaultspec_rag/tests/_cli_helpers.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`

## Notes

The three integration scenarios collected successfully, but their live run was
not available because the GPU fixture found no ready compatible resident
machine-pointer service before pytest isolated its managed paths. Dead searches
confirmed that the superseded timeout diagnostic helpers have no remaining
references.
