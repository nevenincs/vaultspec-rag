---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8feb280ec73d7baae66163f22b90399315b84cef4cd1778c494e9cdc372184ac'
step_id: 'S25'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Carry per-domain facts through route dispatch and require all-source authority for empty aggregate

## Scope

- `src/vaultspec_rag/server/_routes_search.py`

## Changes

- `M` `src/vaultspec_rag/server/_routes_search.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_http_search_errors.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_server.py -q` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_search.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
