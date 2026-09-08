---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:840731d369b518030a381b12c5bd7f1a8c2cd7ee38270868b8acf9d7e5341139'
step_id: 'S45'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Mutation-prove the MCP structured-failure preservation guard

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
