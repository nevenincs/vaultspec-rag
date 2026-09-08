---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:cae01c4abf5a6d7084f47c32a91acec8bb1b68d61d226f50b9f67a7916c4ac6c'
step_id: 'S18'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Assert service, HTTP, CLI, and MCP controller telemetry conformance

## Scope

- `src/vaultspec_rag/tests/integration/test_service_state.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_cli_watcher.py`
- `A` `src/vaultspec_rag/tests/test_controller_surface_conformance.py`
- `verify:` `uv run ruff format src/vaultspec_rag/tests/test_controller_surface_conformance.py src/vaultspec_rag/tests/test_cli_watcher.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/tests/test_controller_surface_conformance.py src/vaultspec_rag/tests/test_cli_watcher.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/tests/test_controller_surface_conformance.py src/vaultspec_rag/tests/test_cli_watcher.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_controller_surface_conformance.py src/vaultspec_rag/tests/test_cli_watcher.py` -> `pass`

## Notes

- Resident selector unavailable: no ready compatible machine-pointer service was captured before pytest isolated its managed paths.
