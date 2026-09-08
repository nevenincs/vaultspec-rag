---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cc9c9488e18bc25562d83e1da8e9445d52abfcba78b964f5c3ee24226ca4d730'
step_id: 'S15'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Adapt controller state and stable reasons through CLI and MCP clients

## Scope

- `src/vaultspec_rag/cli`

## Changes

- `M` `src/vaultspec_rag/cli/_service_watcher.py`
- `M` `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- `M` `src/vaultspec_rag/mcp/_admin_client.py`
- `M` `src/vaultspec_rag/serviceclient/_transport.py`
- `M` `src/vaultspec_rag/tests/test_cli_watcher.py`
- `A` `src/vaultspec_rag/tests/test_controller_client_adapters.py`
- `verify:` `uv run ruff format src/vaultspec_rag/cli/_service_watcher.py src/vaultspec_rag/cli/_service_jobs_presentation.py src/vaultspec_rag/mcp/_admin_client.py src/vaultspec_rag/serviceclient/_transport.py src/vaultspec_rag/tests/test_cli_watcher.py src/vaultspec_rag/tests/test_controller_client_adapters.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/cli/_service_watcher.py src/vaultspec_rag/cli/_service_jobs_presentation.py src/vaultspec_rag/mcp/_admin_client.py src/vaultspec_rag/serviceclient/_transport.py src/vaultspec_rag/tests/test_cli_watcher.py src/vaultspec_rag/tests/test_controller_client_adapters.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/cli/_service_watcher.py src/vaultspec_rag/cli/_service_jobs_presentation.py src/vaultspec_rag/mcp/_admin_client.py src/vaultspec_rag/serviceclient/_transport.py src/vaultspec_rag/tests/test_cli_watcher.py src/vaultspec_rag/tests/test_controller_client_adapters.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_cli_watcher.py src/vaultspec_rag/tests/test_controller_client_adapters.py` -> `pass`
