---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:2e0512d27c4d13fc40316f21317f5bb4b4113b5833ca1e7945c7065c93f6e8e9'
step_id: 'S49'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Apply the readiness scenario matrix to official-client MCP structured responses

## Scope

- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`

## Changes

- `M` `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run pytest --collect-only src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/integration/test_service_search_diagnostics_mcp.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
