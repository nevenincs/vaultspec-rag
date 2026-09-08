---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:bd974e38317fa815610a3afd741c1cd278c537163577476a5c7e19e9ce425e75'
step_id: 'S48'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Apply the readiness scenario matrix to CLI JSON and human rendering

## Scope

- `src/vaultspec_rag/tests/_search_readiness_scenarios.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `and src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`

## Changes

- `M` `src/vaultspec_rag/tests/_search_readiness_scenarios.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`
- `verify:` `uv run pytest -m unit src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/_search_readiness_scenarios.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/_search_readiness_scenarios.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/_search_readiness_scenarios.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/_search_readiness_scenarios.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
