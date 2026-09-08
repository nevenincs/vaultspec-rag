---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:5e35354aa4386af3b1273aed352d9f1fcad52c783d0bafe3c004d4a62981b903'
step_id: 'S22'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Mutation-prove empty authority and Retry-After guards

## Scope

- `src/vaultspec_rag/tests/test_http_search_errors.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_http_search_errors.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
