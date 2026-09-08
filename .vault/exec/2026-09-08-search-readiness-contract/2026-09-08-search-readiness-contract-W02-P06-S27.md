---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ae648bebfe0a1d6f30fe92c60ebef4329bf084f2ae0305de96ef27e6ad5e06a6'
step_id: 'S27'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove combined HTTP no longer bypasses classification or hides constituent failure

## Scope

- `src/vaultspec_rag/tests/test_http_search_errors.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_http_search_errors.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_http_search_errors.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/search/_outcomes.py src/vaultspec_rag/_public_search.py` -> `pass`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_search_outcomes.py src/vaultspec_rag/tests/test_server.py src/vaultspec_rag/tests/test_cli_search.py -q` -> `pass`
- `verify:` `git diff --check` -> `pass`
