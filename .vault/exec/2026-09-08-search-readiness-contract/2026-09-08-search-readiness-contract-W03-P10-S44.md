---
tags:
  - '#exec'
  - '#search-readiness-contract'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:8add401081d1ed355ebe2653ee3baa44fa4b73dc926ed80f4a8336b42f3e2bfe'
step_id: 'S44'
related:
  - "[[2026-09-08-search-readiness-contract-plan]]"
---

# Prove MCP schemas expose bounded policy consistently for every search source

## Scope

- `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`
- `verify:` `uv run pytest src/vaultspec_rag/tests/test_mcp_conformance_surface.py` -> `pass`
- `verify:` `uv run ruff format --check src/vaultspec_rag/tests/test_mcp_conformance_surface.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_mcp_conformance_surface.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_mcp_conformance_surface.py` -> `pass`
- `verify:` `uv run basedpyright src/vaultspec_rag/tests/test_mcp_conformance_surface.py` -> `pass`
- `verify:` `git diff --check` -> `pass`
