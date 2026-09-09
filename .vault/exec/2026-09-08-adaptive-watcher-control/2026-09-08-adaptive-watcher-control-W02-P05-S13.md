---
tags:
  - '#exec'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:1792aa6604988e9c6d7d297b274430d427cfc30ff68cf4ca9fd1a0ea2d5cc5e0'
step_id: 'S13'
related:
  - "[[2026-09-08-adaptive-watcher-control-plan]]"
---

# Add canonical controller snapshots and structured transition evidence to service state, jobs, and logs

## Scope

- `src/vaultspec_rag/api.py`

## Changes

- `M` `src/vaultspec_rag/api.py`
- `M` `src/vaultspec_rag/server/_watcher.py`
- `A` `src/vaultspec_rag/tests/test_controller_projection.py`
- `verify:` `uv run --no-sync ruff format src/vaultspec_rag/api.py src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_controller_projection.py` -> `pass`
- `verify:` `uv run --no-sync ruff check src/vaultspec_rag/api.py src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_controller_projection.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_rag/api.py src/vaultspec_rag/server/_watcher.py src/vaultspec_rag/tests/test_controller_projection.py` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_controller_projection.py src/vaultspec_rag/tests/test_watcher_scheduler.py -q` -> `pass`
