---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:1171c0ff7fb1653d23ce1ad0b1ea386b0e5affe2e74cae6c940315e9ff1df613'
step_id: 'S43'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove every MCP search tool preserves structured success and failure through the official client

## Scope

- `src/vaultspec_rag/mcp/_tools.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`
- `and src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`

## Changes

- `M` `src/vaultspec_rag/mcp/_tools.py`
- `D` `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`
- `A` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`
- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
