---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:db1ed40e328efcc58eb5d8afa72b1569a4645bbefabe2ed32e710413e5fa742d'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# `search-readiness-contract` `W02.P07` summary

## Changes

- `M` `src/vaultspec_rag/search/_searcher.py`
- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/server/_search_activity.py`
- `M` `src/vaultspec_rag/tests/test_search_activity.py`
- `M` `src/vaultspec_rag/tests/test_service_search_diagnostics.py`
- `verify:` `uv run basedpyright src/vaultspec_rag/server/_search_activity.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_activity.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_unit.py src/vaultspec_rag/tests/test_search_quality_fixes_unit.py src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `git diff --check -- src/vaultspec_rag/search/_searcher.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_search_activity.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_server.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_outcomes.py -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py -q` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_search_unit.py src/vaultspec_rag/tests/test_search_quality_fixes_unit.py -q` -> `pass` (`162 passed`)
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_readiness.py src/vaultspec_rag/tests/test_search_quiesce_admission.py -q` -> `pass` (`129 passed`)
- `verify:` representative immediate, bounded-timeout, partial-success, partial-empty-failure, and complete-failure HTTP envelope assertions -> `pass` (`5 passed`; failures omit results and inferred `Retry-After`, combined responses retain all requested source facts)
