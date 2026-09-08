---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:ef90df447901b6095a227d4132cc218c144562b3bc745f6c7981a1ef8bdfabf4'
step_id: 'S42'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Replace opaque RuntimeError reduction with structured error content and actionable text

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
