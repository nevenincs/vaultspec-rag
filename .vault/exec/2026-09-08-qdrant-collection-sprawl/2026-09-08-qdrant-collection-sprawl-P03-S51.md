---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:f248ba9c75bca961b19f6ce953a6c0a7450537643ce003a957cd5ffc8260cbc0'
step_id: 'S51'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Collapse the duplicated status summary renderers behind one implementation taking the values that differ

## Scope

- `src/vaultspec_rag/cli/_status_render.py`

## Changes

- `M` `src/vaultspec_rag/cli/_status_render.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_process_probe_source_structure.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_cli_service_status.py src/vaultspec_rag/tests/test_cli_status.py src/vaultspec_rag/tests/test_jobs_tui_status.py` -> `pass`
