---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:d650c63b8141cd0a0a83c0400d53860486af8b7ae197a3536be07aba5b7bb161'
step_id: 'S41'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Extend MCP input and result models with policy and canonical readiness content

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Changes

- `M` `src/vaultspec_rag/mcp/_tools.py`
- `M` `src/vaultspec_rag/tests/test_mcp_no_local_fallback.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_mcp_conformance_surface.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py src/vaultspec_rag/tests/test_mcp_project_root.py src/vaultspec_rag/tests/test_mcp_import_isolation.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
