---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:b80bf2c6a8f99c2e64f395e16164901b1803308847cb1b1b51b553c570d97145'
step_id: 'S47'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Apply the readiness scenario matrix to real HTTP responses and headers

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `verify:` `uv run pytest -m unit src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
