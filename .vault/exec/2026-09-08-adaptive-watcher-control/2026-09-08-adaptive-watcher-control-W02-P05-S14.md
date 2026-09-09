---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:1962b1a33fab1cb1983fa4edfe9fbb8403888197bffb0fdab86113742d5caf58'
step_id: 'S14'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Project identical controller facts through watcher and job HTTP routes

## Scope

- `src/vaultspec_rag/server`

## Changes

- `M` `src/vaultspec_rag/server/_routes_registry.py`
- `M` `src/vaultspec_rag/server/_routes_jobs.py`
- `A` `src/vaultspec_rag/tests/test_watcher_route_projection.py`
- `verify:` `uv run ruff format src/vaultspec_rag/server/_routes_registry.py src/vaultspec_rag/server/_routes_jobs.py src/vaultspec_rag/tests/test_watcher_route_projection.py` -> `pass`
- `verify:` `uv run ruff check src/vaultspec_rag/server/_routes_registry.py src/vaultspec_rag/server/_routes_jobs.py src/vaultspec_rag/tests/test_watcher_route_projection.py` -> `pass`
- `verify:` `uv run ty check src/vaultspec_rag/server/_routes_registry.py src/vaultspec_rag/server/_routes_jobs.py src/vaultspec_rag/tests/test_watcher_route_projection.py` -> `pass`
- `verify:` `uv run pytest -q src/vaultspec_rag/tests/test_watcher_route_projection.py` -> `pass`
