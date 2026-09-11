---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cbb4845efbcec94749e1bc28a5048635e8eab941d9ad5e2b0bc9866de2ae7b10'
step_id: 'S33'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove every named wait cause remains distinct under contention

## Scope

- `src/vaultspec_rag/tests/test_service_search_diagnostics.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_service_search_diagnostics.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_service_search_diagnostics.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_search_activity.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_outcomes.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
