---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:1d0511a1318f436f64df89855b20f485ef7f1c653f95b31e143f7c03e1a5c7f5'
step_id: 'S16'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove policy defaults validation stable targets typed timeout and disconnect behavior

## Scope

- `src/vaultspec_rag/tests/test_http_search_routing.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `M` `src/vaultspec_rag/server/_search_readiness.py`
- `M` `src/vaultspec_rag/tests/test_http_search_routing.py`
- `M` `src/vaultspec_rag/tests/test_search_readiness.py`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py src/vaultspec_rag/server/_search_readiness.py src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_readiness.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_http_search_routing.py src/vaultspec_rag/tests/test_search_readiness.py src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_server.py --disable-warnings` -> `pass`
- `verify:` `git diff --check` -> `pass`
