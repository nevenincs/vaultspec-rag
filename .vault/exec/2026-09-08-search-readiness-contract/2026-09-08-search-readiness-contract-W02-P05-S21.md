---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:1011263ec31ad18eda35c39cf221694c6cc72f2db59f267c05f87196068716be'
step_id: 'S21'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Cover stable failures updating success empty authority result suppression status and header truthfulness

## Scope

- `src/vaultspec_rag/tests/test_http_search_errors.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/server/_search_availability.py`
- `M` `src/vaultspec_rag/tests/test_http_search_errors.py`
- `M` `src/vaultspec_rag/tests/test_http_search_routing.py`
- `M` `src/vaultspec_rag/tests/test_search_availability.py`
- `M` `src/vaultspec_rag/tests/test_service_search_diagnostics.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_availability.py src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_server.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_availability.py src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_availability.py src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_availability.py src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
